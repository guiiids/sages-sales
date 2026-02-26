#app/persistence/db_api.py

#=====================================================================================================#
#Copyright (c) 2026 Agilent Technologies All rights reserved worldwide.
#Agilent Confidential, Use is permitted only in accordance with applicable End User License Agreement.
#=====================================================================================================#

from datetime import datetime, timedelta
import logging

from sqlalchemy import text, func, cast, Date
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.models.models import User, UserSessions, Queries, QueryDetails, Feedback, OpenAIUsage, GroundednessEvaluation
from app.persistence.orm import Engine

logger = logging.getLogger(__name__)

class Connection:
    """
    Manages database connections and provides methods to interact with the database.
    Uses scoped_session so each thread/request gets its own isolated session.
    """

    def __init__(self, hostname, port, username, password, database, schema_name="public", ssl_mode="disable"):
        """
        Initializes the Connection object and creates a scoped session factory.
        """
        self._engine = None
        self._Session = None  # scoped_session factory (thread-safe registry)
        self.entity_master_map = None
        self.create_new_session(hostname, port, username, password, database, schema_name, ssl_mode)

    def create_new_session(self, hostname, port, username, password, database, schema_name="public", ssl_mode="disable"):
        """
        Creates the engine and scoped_session factory.
        """
        if self._engine:
            self._engine.create_new_session(hostname, port, username, password, database, schema_name, ssl_mode)
        else:
            # Pass pool options to Engine
            self._engine = Engine(
                hostname, port, username, password, database, schema_name, ssl_mode,
                poolclass=QueuePool,
                pool_size=10,  # max connections in pool
                max_overflow=20,  # extra connections beyond pool_size
                pool_timeout=30,  # seconds to wait before giving up on getting a connection
                pool_recycle=1800,  # recycle connections after 30 minutes
                pool_pre_ping=True
            )

        # scoped_session: each thread gets its own Session from the registry
        self._Session = scoped_session(sessionmaker(bind=self._engine.engine))

    @property
    def db(self):
        """Returns the thread-local session from the scoped_session registry."""
        return self._Session()

    def ensure_healthy_session(self):
        """Reset session if it's in a bad state (prepared/failed/inactive)."""
        try:
            session = self._Session()
            if not session.is_active:
                logger.warning("Session not active, rolling back and removing")
                try:
                    session.rollback()
                except Exception:
                    pass
                self._Session.remove()
        except Exception as e:
            logger.warning(f"Session health check failed, removing: {e}")
            try:
                self._Session.remove()
            except Exception:
                pass

    def remove_session(self):
        """Remove the current scoped session (call at end of request)."""
        if self._Session:
            try:
                self._Session.remove()
            except Exception as e:
                logger.warning(f"Error removing scoped session: {e}")

    # def row_to_dict(self,row):
    #     return {c.name: getattr(row, c.name) for c in row.__table__.columns}

    def row_to_dict(self, row):
        # Single ORM model
        if hasattr(row, '__table__'):
            return {c.name: getattr(row, c.name) for c in row.__table__.columns}
        # Named tuple (e.g., from .label or ._asdict)
        if hasattr(row, '_fields'):
            result = {}
            for field in row._fields:
                item = getattr(row, field)
                if hasattr(item, '__table__'):
                    result.update({c.name: getattr(item, c.name) for c in item.__table__.columns})
                else:
                    # For scalar columns, try to get the key/label
                    key = getattr(item, 'key', None) or getattr(item, 'name', None)
                    if key:
                        result[key] = item
                    elif isinstance(field,str):
                        result[field] = item
            return result
        # Fallback: return as-is
        return dict(row) if hasattr(row, 'keys') else {'value': row}

    def get_data_by_Attributes(self, model, **attributes):
        """
        Retrieves records from the database matching the given model and attribute filters.
        """
        criterion = [getattr(model, attribute_key) == attribute_val for attribute_key, attribute_val in attributes.items()]
        matches = self.db.query(model).filter(*criterion).all()
        return matches

    def get_user_by_ad_user_id_hash(self, ad_user_id_hash):
        """
        Retrieves a user by their Active Directory user ID.
        """
        users = self.get_data_by_Attributes(User, ad_user_id_hash=ad_user_id_hash)
        return users[0] if users else None

    def save_data(self, data):
        """
        Adds and commits a data object to the database. Rolls back on error.
        """
        try:
            self.db.add(data)
            self.db.commit()
            return data
        except Exception as err:
            self.db.rollback()
            logger.error(err)

    def save_user(self, user: User):
        """
        Saves a User object to the database.
        """
        return self.save_data(user)

    def save_user_session(self, user_session: UserSessions):
        """
        Saves a UserSessions object to the database.
        """
        return self.save_data(user_session)

    def save_query(self, query: Queries):
        """
        Saves a Queries object to the database.
        """
        return self.save_data(query)

    def save_query_details(self, query_details: QueryDetails):
        """
        Saves a QueryDetails object to the database.
        """
        return self.save_data(query_details)

    def save_openai_usage(self, openai_usage):
        """
        Saves an OpenAIUsage object to the database.
        """
        return self.save_data(openai_usage)

    def save_feedback(self, feedback: Feedback):
        """
        Saves a Feedback object to the database.
        """
        return self.save_data(feedback)

    def save_self_critique_metrics(self, self_critique_metrics):
        """
        Saves a SelfCritiqueMetrics object to the database.
        """
        return self.save_data(self_critique_metrics)

    def save_groundenss_evaluation(self,groundness_evaluation):
        """
        Saves a GroundnessEvaluation object to the database.
        """
        return self.save_data(groundness_evaluation)

    def test_connection(self):
        """
        Tests the database connection by executing a simple query.
        """
        try:
            result = self.db.execute(text('SELECT 1;'))
            return result.scalar() == 1
        except Exception as e:
            self.db.rollback()
            logger.error(f"Database connection test failed: {e}")
            return False

    # function to fetch the queries count in date range, if no date range provided fetch all
    def fetch_queries_count_in_date_range(self, start_date=None, end_date=None):
        """
        Fetches the count of queries within the specified date range. If no range is provided, fetches count of all queries.
        """
        try:
            query = self.db.query(Queries)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            return query.count()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching queries count: {e}")
            return 0

    # fetch avg latency metrics of llm,reranker and search using sqlalchemy join query and query details table for date filtering
    def fetch_query_latency_metrics(self, start_date=None, end_date=None):
        """
        Fetches average latency metrics for LLM, reranker, and search within the specified date range.
        """
        try:
            query = self.db.query(
                func.avg(QueryDetails.latency_ms).label('avg_latency'),
                func.avg(QueryDetails.llm_latency_ms).label('avg_llm_latency'),
                func.avg(QueryDetails.reranker_latency_ms).label('avg_reranker_latency'),
                func.avg(QueryDetails.search_latency_ms).label('avg_search_latency'),
                func.percentile_cont(0.5).within_group(QueryDetails.latency_ms).label('p50'),
                func.percentile_cont(0.9).within_group(QueryDetails.latency_ms).label('p90'),
                func.percentile_cont(0.95).within_group(QueryDetails.latency_ms).label('p95'),
                func.percentile_cont(0.99).within_group(QueryDetails.latency_ms).label('p99')
            ).join(Queries, QueryDetails.query_id == Queries.query_id)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            return query.one()._asdict()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching latency metrics: {e}")
            return {}

    # function to fetch token usage metrics in date range along with cost, joining with queries table for date filtering
    def fetch_token_usage_metrics(self, start_date=None, end_date=None):
        """
        Fetches token usage metrics along with cost within the specified date range.
        """
        try:
            query = self.db.query(
                func.coalesce(func.sum(OpenAIUsage.prompt_tokens), 0).label('prompt_tokens'),
                func.coalesce(func.sum(OpenAIUsage.completion_tokens), 0).label('completion_tokens'),
                func.coalesce(func.sum(OpenAIUsage.total_tokens), 0).label('total_tokens'),
                func.coalesce(func.sum(OpenAIUsage.total_cost), 0).label('cost_total'),
                func.coalesce(func.sum(OpenAIUsage.prompt_cost), 0).label('cost_prompt'),
                func.coalesce(func.sum(OpenAIUsage.completion_cost), 0).label('cost_completion')
            ).join(Queries, OpenAIUsage.query_id == Queries.query_id)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            return query.one()._asdict()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching token usage metrics: {e}")
            return {}

    # function to fetch streaming vs standard query counts in date range, joining with query details table for date filtering
    def fetch_streaming_standard_query_counts(self, start_date=None, end_date=None):
        """
        Fetches counts of streaming (follow-up) vs standard (initial) queries within the specified date range.
        """
        try:
            query = self.db.query(
                func.count().filter(QueryDetails.is_follow_up == True).label('followup_count'),
                func.count().filter((QueryDetails.is_follow_up == False) | (QueryDetails.is_follow_up is None)).label('initial_count')
            ).join(Queries, QueryDetails.query_id == Queries.query_id)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            return query.one()._asdict()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching streaming vs standard query counts: {e}")
            return {}

    # function to fetch model distribution in date range, joining with queries table for date filtering
    def fetch_model_distribution(self, start_date=None, end_date=None, limit=5):
        """
        Fetches the distribution of models used in queries within the specified date range.
        """
        try:
            query = self.db.query(
                OpenAIUsage.model.label('model'),
                func.count().label('count')
            )
            if start_date:
                query = query.filter(OpenAIUsage.timestamp >= start_date)
            if end_date:
                query = query.filter(OpenAIUsage.timestamp <= end_date)
            query = query.group_by(OpenAIUsage.model).order_by(func.count().desc()).limit(limit)
            return [row._asdict() for row in query.all()]

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching model distribution: {e}")
            return []

    # function to fetch query quality metrics in date range, joining  queries and QueryDetails able for date filtering
    def fetch_query_quality_metrics(self, start_date=None, end_date=None):
        """
        Fetches quality metrics of queries within the specified date range.
        """
        try:
            query = self.db.query(
                func.avg(func.length(QueryDetails.response)).label('avg_response_length'),
                func.count().filter(func.length(QueryDetails.response) < 50).label('short_responses')
            ).join(Queries, QueryDetails.query_id == Queries.query_id)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            return query.one()._asdict()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching query quality metrics: {e}")
            return {}

    # function to fetch citation metrics in date range, joining with queries and query details table for date filtering
    def fetch_query_citation_metrics(self, start_date=None, end_date=None):
        """
        Fetches citation metrics of queries within the specified date range.
        """
        try:
            query = self.db.query(
                func.avg(func.jsonb_array_length(QueryDetails.sources)).label('avg_citations'),
                func.count().filter(func.jsonb_array_length(QueryDetails.sources) > 0).label('with_citations')
            ).join(Queries, QueryDetails.query_id == Queries.query_id)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            return query.one()._asdict()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching citation metrics: {e}")
            return []

    # function fetch daily query trend in date range
    def fetch_daily_query_trend(self, start_date=None, end_date=None):
        """
        Fetches daily query trend within the specified date range.
        """
        try:
            query = self.db.query(
                func.date(Queries.timestamp).label('day'),
                func.count().label('count')
            )
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            query = query.group_by(func.date(Queries.timestamp)).order_by(func.date(Queries.timestamp).asc())
            return [row._asdict() for row in query.all()]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching daily query trend: {e}")
            return []

    # Function to fetch recent feedback metrics total_feedback, positive(if tag contains helpful) and negative in date range
    def fetch_feedback_metrics(self, start_date=None, end_date=None):
        """
        Fetches feedback metrics including total, positive, and negative feedback within the specified date range.
        """
        try:
            query = self.db.query(
                func.count().label('total_feedback'),
                func.count().filter(Feedback.feedback_tags.any('helpful')).label('positive_feedback'),
                func.count().filter(~Feedback.feedback_tags.any('helpful')).label('negative_feedback')

            )
            if start_date:
                query = query.filter(Feedback.timestamp >= start_date)
            if end_date:
                query = query.filter(Feedback.timestamp <= end_date)
            return query.one()._asdict()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching feedback metrics: {e}")
            return {}


    # function to fetch feedback tag distribution in date range
    def fetch_feedback_tag_distribution(self, start_date=None, end_date=None, limit=10):
        """
        Fetches the distribution of feedback tags within the specified date range.
        """
        try:
            query = self.db.query(
                func.unnest(Feedback.feedback_tags).label('tag'),
                func.count().label('count')
            )
            if start_date:
                query = query.filter(Feedback.timestamp >= start_date)
            if end_date:
                query = query.filter(Feedback.timestamp <= end_date)
            query = query.group_by('tag').order_by(func.count().desc()).limit(limit)
            return [row._asdict() for row in query.all()]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching feedback tag distribution: {e}")
            return []

    # function to fetch recent feedback in date range
    def fetch_recent_feedback(self, start_date=None, end_date=None, limit=10):
        """
        Fetches recent feedback entries within the specified date range.
        """
        try:
            query = self.db.query(
                #Feedback, QueryDetails.user_query.label('user_query')
                Feedback, QueryDetails
            ).join(QueryDetails, Feedback.query_id == QueryDetails.query_id)
            if start_date:
                query = query.filter(Feedback.timestamp >= start_date)
            if end_date:
                query = query.filter(Feedback.timestamp <= end_date)
            query = query.order_by(Feedback.timestamp.desc()).limit(limit)
            return [self.row_to_dict(row) for row in query.all()]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching recent feedback: {e}")
            return []

    # function to fetch raw openai usage logs in date range
    def fetch_openai_usage_logs(self, start_date=None, end_date=None, limit=100):
        """
        Fetches raw OpenAI usage logs within the specified date range.
        """
        try:
            query = self.db.query(OpenAIUsage).join(Queries, OpenAIUsage.query_id == Queries.query_id)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            query = query.order_by(OpenAIUsage.timestamp.desc()).limit(limit)
            return [self.row_to_dict(row) for row in query.all()]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching OpenAI usage logs: {e}")
            return []

    # function to get mode distribution in date range, joining with queries and query details table for date filtering
    def fetch_mode_distribution(self, start_date=None, end_date=None):
        """
        Fetches the distribution of modes (e.g., chat, completion) used in queries within the specified date range.
        """
        try:
            query = self.db.query(
                QueryDetails.mode,
                func.count().label('count')
            ).join(Queries, QueryDetails.query_id == Queries.query_id)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            query = query.group_by(QueryDetails.mode).order_by(func.count().desc())
            return [row._asdict() for row in query.all()]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching mode distribution: {e}")
            return []

    # Function to get persona distribution in date range, joining with queries and query details table for date filtering
    def fetch_persona_distribution(self, start_date=None, end_date=None):
        """
        Fetches the distribution of personas used in queries within the specified date range.
        """
        try:
            query = self.db.query(
                QueryDetails.persona,
                func.count().label('count')
            ).join(Queries, QueryDetails.query_id == Queries.query_id)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            query = query.group_by(QueryDetails.persona).order_by(func.count().desc())
            return [row._asdict() for row in query.all()]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching persona distribution: {e}")
            return []

# function to get persona metrics in date range, joining with openaiusage and query details table for persona and date filtering
    def fetch_persona_metrics(self, start_date=None, end_date=None):
        """
        Fetches per-persona metrics: query count, avg latency, avg tokens, total tokens, total cost, avg cost per query.
        Handles multiple OpenAIUsage records per query by aggregating cost per query first.
        """

        try:
            # Subquery: total cost per query
            query_cost_subq = (
                self.db.query(
                    OpenAIUsage.query_id,
                    func.sum(OpenAIUsage.total_cost).label('query_total_cost'),
                    func.sum(OpenAIUsage.total_tokens).label('query_total_tokens'),
                    func.sum(OpenAIUsage.completion_tokens).label('query_total_completion_tokens'),
                )
                .group_by(OpenAIUsage.query_id)
                .subquery()
            )

            # Main query: metrics per persona
            query = (
                self.db.query(
                    QueryDetails.persona,
                    func.count(QueryDetails.query_id).label('query_count'),
                    func.avg(QueryDetails.latency_ms).label('avg_latency'),
                    func.avg(query_cost_subq.c.query_total_tokens).label('avg_tokens'),
                    func.sum(query_cost_subq.c.query_total_tokens).label('total_tokens'),
                    func.sum(query_cost_subq.c.query_total_cost).label('total_cost'),
                    func.avg(query_cost_subq.c.query_total_cost).label('avg_cost_per_query')
                )
                .join(Queries, QueryDetails.query_id == Queries.query_id)
                .join(query_cost_subq, query_cost_subq.c.query_id == Queries.query_id)
            )
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            query = query.group_by(QueryDetails.persona).order_by(func.count(QueryDetails.query_id).desc())
            return [row._asdict() for row in query.all()]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching persona metrics: {e}")
            return []

    # Daily breakdown of experimental vs production queries
    def fetch_experimental_production_query_trend(self, start_date=None, end_date=None):
        """
        Fetches daily breakdown of query counts grouped by date and mode.
        """
        try:
            query = self.db.query(
                func.date(Queries.timestamp).label('date'),
                QueryDetails.mode,
                func.count().label('count')
            ).join(QueryDetails, QueryDetails.query_id == Queries.query_id)
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            query = query.group_by(func.date(Queries.timestamp), QueryDetails.mode).order_by(func.date(Queries.timestamp).asc())
            return [row._asdict() for row in query.all()]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching experimental vs production query trend: {e}")
            return []

    # ===== RECENT EXPERIMENTAL QUERIES =====
    def fetch_recent_experimental_queries(self, start_date=None, end_date=None, limit=10):
        """
        Fetches recent experimental queries (mode='experiment') within the specified date range.
        """
        try:
            query = self.db.query(Queries).join(QueryDetails, QueryDetails.query_id == Queries.query_id).filter(QueryDetails.mode == 'experimental')
            if start_date:
                query = query.filter(Queries.timestamp >= start_date)
            if end_date:
                query = query.filter(Queries.timestamp <= end_date)
            query = query.order_by(Queries.timestamp.desc()).limit(limit)
            return [self.row_to_dict(row) for row in query.all()]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching recent experimental queries: {e}")
            return []

    def get_users_count(self):
        """
        Retrieves the total count of users in DB.
        """
        try:
            count = self.db.query(func.count(User.user_id)).scalar()
            return count
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching users count: {e}")
            return 0

    def get_active_users_count(self, start_date, end_date):
        """
        Retrieves the count of active users in date range.
        """
        try:
            count = (self.db.query(func.count(func.distinct(UserSessions.user_id)))
                     .filter(UserSessions.session_start_timestamp >= start_date, UserSessions.session_start_timestamp <= end_date).scalar())
            return count
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching active users count: {e}")
            return 0

    def get_queries_count(self, start_date, end_date):
        """
        Retrieves the count of queries in date range.
        """
        try:
            count = (self.db.query(func.count(Queries.query_id))
                     .filter(Queries.timestamp >= start_date, Queries.timestamp <= end_date).scalar())
            return count
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching queries count: {e}")
            return 0

    def get_user_sessions_percentile(self, start_percentile,end_percentile, start_date, end_date):
        """
        Retrieves the count of users whose session counts are above the given percentile in date range.
        """
        try:
            # Subquery: count unique session days per user
            subquery = (
                self.db.query(
                    UserSessions.user_id,
                    func.count(func.distinct(cast(UserSessions.session_start_timestamp, Date))).label('session_days')
                )
                .filter(
                    UserSessions.session_start_timestamp >= start_date,
                    UserSessions.session_start_timestamp <= end_date
                )
                .group_by(UserSessions.user_id)
            ).subquery()

            # Calculate the threshold session_days for the given percentile
            start_threshold = (
                self.db.query(
                    func.percentile_cont(start_percentile / 100.0).within_group(subquery.c.session_days)
                )
            ).scalar()

            end_threshold = (
                self.db.query(
                    func.percentile_cont(end_percentile / 100.0).within_group(subquery.c.session_days)
                )
            ).scalar()

            # Count users above the threshold
            count = (
                self.db.query(func.count())
                .select_from(subquery)
                .filter(subquery.c.session_days > start_threshold, subquery.c.session_days <= end_threshold).scalar()
            )

            return count
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching user sessions percentile: {e}")
            return 0

    def get_average_sessions_per_week(self, start_date, end_date):
        """
        Retrieves the average number of sessions per week in date range.
        """
        try:
            total_weeks = ((end_date - start_date).days) / 7.0
            total_sessions = (self.db.query(func.count(UserSessions.session_id))
                              .filter(UserSessions.session_start_timestamp >= start_date,
                                      UserSessions.session_start_timestamp <= end_date).scalar())
            avg_sessions_per_week = total_sessions / total_weeks if total_weeks > 0 else 0
            return round(avg_sessions_per_week,1)
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching average sessions per week: {e}")
            return 0

    def get_average_messages_per_session(self, start_date, end_date):
        """
        Retrieves the average number of messages per session in date range.
        """
        try:
            total_sessions = (self.db.query(func.count(UserSessions.session_id))
                              .filter(UserSessions.session_start_timestamp >= start_date,
                                      UserSessions.session_start_timestamp <= end_date).scalar())
            total_queries = (self.db.query(func.count(Queries.query_id))
                             .filter(Queries.timestamp >= start_date,
                                     Queries.timestamp <= end_date).scalar())
            avg_messages_per_session = total_queries / total_sessions if total_sessions > 0 else 0
            return round(avg_messages_per_session,1)
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching average messages per session: {e}")
            return 0

    def get_average_queries_per_user(self, start_date, end_date):
        """
        Retrieves the average number of queries per user in date range.
        """
        try:
            total_users = (self.db.query(func.count(func.distinct(UserSessions.user_id)))
                .select_from(Queries)
                .join(UserSessions, Queries.session_id == UserSessions.id)
                .filter(Queries.timestamp >= start_date, Queries.timestamp <= end_date)
                .scalar())
            total_queries = (self.db.query(func.count(Queries.query_id))
                             .filter(Queries.timestamp >= start_date,
                                     Queries.timestamp <= end_date).scalar())
            logger.debug(f"Total users: {total_users} and total queries: {total_queries} in date range {start_date} to {end_date}")
            avg_queries_per_user = total_queries / total_users if total_users > 0 else 0
            return round(avg_queries_per_user,1)
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching average queries per user: {e}")
            return 0

    def get_weekly_active_user(self, start_date, end_date):
        """
        Retrive total weekly active user
        """
        try:
            weekly_active_rows = (
                self.db.query(
                    func.date_trunc('week', UserSessions.session_start_timestamp).label('week'),
                    func.count(func.distinct(UserSessions.user_id)).label('count')
                )
                .filter(
                    UserSessions.session_start_timestamp >= start_date,
                    UserSessions.session_start_timestamp < end_date
                )
                .group_by('week')
                .order_by('week')
                .all()
            )

            active_by_week = {row.week.date(): row.count for row in weekly_active_rows}
            week_starts = [start_date + timedelta(weeks=i) for i in range(12)]
            weekly_active_users = [active_by_week.get(ws.date(), 0) for ws in week_starts]

            return weekly_active_users
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error while fetching weekly active user: {e}")
            return []

    def get_weekly_queries(self, start_date, end_date):
        """
        Retrive total weekly queries
        """
        try:
            weekly_query_rows = (
                self.db.query(
                    func.date_trunc('week', Queries.timestamp).label('week'),
                    func.count(Queries.query_id).label('count')
                )
                .filter(
                    Queries.timestamp >= start_date,
                    Queries.timestamp < end_date
                )
                .group_by('week')
                .order_by('week')
                .all()
            )

            queries_by_week = {row.week.date(): row.count for row in weekly_query_rows}
            week_starts = [start_date + timedelta(weeks=i) for i in range(12)]
            weekly_queries = [queries_by_week.get(ws.date(), 0) for ws in week_starts]

            return weekly_queries
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error while fetching weekly queries: {e}")
            return []

    def get_groundedness_evaluations(self, limit):
        """
        Fetches a limited number of groundedness evaluation records.
        """
        try:
            # query = self.db.query(GroundednessEvaluation).order_by(GroundednessEvaluation.timestamp.desc()).limit(limit)
            query = (
                self.db.query(QueryDetails, GroundednessEvaluation)
                .join(GroundednessEvaluation, QueryDetails.query_id == GroundednessEvaluation.query_id)
                .order_by(GroundednessEvaluation.timestamp.desc())
                .limit(limit)
            )
            results = query.all()
            # Process results for display
            processed = []
            for row in results:
                item = self.row_to_dict(row)
                # Add display-friendly truncated versions
                item['user_query_display'] = (item['user_query'] or '')[:80] + (
                    '...' if item['user_query'] and len(item['user_query']) > 80 else '')
                item['answer_display'] = (item['answer'] or '')[:100] + (
                    '...' if item['answer'] and len(item['answer']) > 100 else '')
                item['user_query_full'] = item['user_query'] or ''
                item['answer_full'] = item['answer'] or ''
                item['context_full'] = item['context_snippet'] or ''
                # Count citations in answer
                import re
                citation_matches = re.findall(r'\[(\d+)\]', item['answer'] or '')
                item['citation_count'] = len(set(citation_matches))
                processed.append(item)

            logger.info(f"Fetched {len(processed)} groundedness evaluations")
            return processed
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching groundedness evaluations: {e}")
            return []

    def get_radar_evaluations(self, limit):
        """
        Fetches queries with non-null features_json and processes them to form the result.
        """
        try:
            query = (self.db.query(QueryDetails,Queries)
                     .join(Queries, QueryDetails.query_id == Queries.query_id)
                     .filter(QueryDetails.features_json.isnot(None))
                     .order_by(Queries.timestamp.desc())
                     .limit(limit))
            processed = []
            res = query.all()
            for row in res:
                item = self.row_to_dict(row)
                features = item.get('features_json') or {}
                radar = features.get('radar_evaluation', {})

                # Skip if no RADAR data
                if not radar:
                    continue

                # Add display-friendly truncated versions
                item['user_query_display'] = (item['user_query'] or '')[:80] + (
                    '...' if item['user_query'] and len(item['user_query']) > 80 else '')
                item['response_display'] = (item['response'] or '')[:100] + (
                    '...' if item['response'] and len(item['response']) > 100 else '')
                item['user_query_full'] = item['user_query'] or ''
                item['response_full'] = item['response'] or ''

                # Extract RADAR-specific fields from radar_evaluation structure
                radar_scores = radar.get('scores', {})
                radar_reasons = radar.get('reasons', {})

                # Determine failing dimensions (score < threshold, default 0.75)
                thresholds = features.get('radar_correction_thresholds', {
                    'query_resolution': 0.7,
                    'factual_accuracy': 0.75,
                    'completeness': 0.7,
                    'clarity': 0.6,
                    'actionability': 0.65,
                    'citation_quality': 0.8
                })
                failing = []
                for dim, score in radar_scores.items():
                    threshold = thresholds.get(dim, 0.75)
                    if score < threshold:
                        failing.append(dim)

                item['was_corrected'] = radar.get('was_corrected', len(failing) > 0)
                item['failing_dimensions'] = failing
                item['radar_scores'] = radar_scores
                item['radar_reasons'] = radar_reasons
                item['corrected_response'] = radar.get('corrected_response', '')
                item['original_draft'] = radar.get('original_draft', '')
                item['total_radar_tokens'] = radar.get('total_radar_tokens', 0)
                item['eval_prompt_tokens'] = radar.get('eval_prompt_tokens', 0)
                item['eval_completion_tokens'] = radar.get('eval_completion_tokens', 0)
                item['correction_prompt_tokens'] = radar.get('correction_prompt_tokens', 0)
                item['correction_completion_tokens'] = radar.get('correction_completion_tokens', 0)

                # Extract thresholds used
                item['radar_thresholds'] = thresholds

                # Count citations in response
                import re
                citation_matches = re.findall(r'\[(\d+)\]', item['response'] or '')
                item['citation_count'] = len(set(citation_matches))

                # Count failing dimensions for display
                item['failing_count'] = len(item['failing_dimensions'])

                processed.append(item)

            logger.info(f"Fetched {len(processed)} RADAR evaluations from features_json")
            return processed
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error fetching radar evaluations: {e}")
            return []

    def set_session_end_time(self, session_id):
        """
        Set the session end timestamp for the provided session
        """
        try:
            user_session = (
                self.db.query(UserSessions)
                .filter(UserSessions.session_id == session_id)
                .order_by(UserSessions.session_start_timestamp.desc())
                .first()
            )
            if user_session:
                user_session.session_end_timestamp = datetime.now()
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to update session_end_timestamp for {session_id}: {e}")

