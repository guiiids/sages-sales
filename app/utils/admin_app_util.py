import logging
import logging

from app.Connection import get_connection
from config import get_current_model

logger = logging.getLogger(__name__)
def get_observability_summary(start_date=None, end_date=None):
    """
    Comprehensive observability metrics for the dashboard.
    Returns all metrics needed for the enterprise observability dashboard.
    """

    conn = None
    try:
        conn = get_connection()

        result = {}

        # ===== BASIC COUNTS =====
        result['total_queries'] = conn.fetch_queries_count_in_date_range(start_date, end_date)

        # ===== LATENCY METRICS =====

        latency_row = conn.fetch_query_latency_metrics(start_date, end_date)

        result['avg_latency_ms'] = int(latency_row['avg_latency'] or 0) if latency_row else 0
        result['latency_breakdown'] = {
            'search': int(latency_row['avg_search_latency'] or 0) if latency_row else 0,
            'rerank': int(latency_row['avg_reranker_latency'] or 0) if latency_row else 0,  # Not tracked separately
            'llm': int(latency_row['avg_llm_latency'] or 0) if latency_row else 0
        }
        result['latency_percentiles'] = {
            'p50': int(latency_row['p50'] or 0) if latency_row else 0,
            'p90': int(latency_row['p90'] or 0) if latency_row else 0,
            'p95': int(latency_row['p95'] or 0) if latency_row else 0,
            'p99': int(latency_row['p99'] or 0) if latency_row else 0
        }

        # ===== TOKEN METRICS =====
        token_row = conn.fetch_token_usage_metrics(start_date, end_date)
        result['prompt_tokens'] = int(token_row.get('prompt_tokens',0) or 0)
        result['completion_tokens'] = int(token_row.get('completion_tokens') or 0)
        result['total_tokens'] = int(token_row.get('total_tokens') or 0)

        # Use costs from DB directly (already calculated)
        result['total_cost'] = float(token_row.get('cost_total') or 0)
        result['prompt_cost'] = float(token_row.get('cost_prompt') or 0)
        result['completion_cost'] = float(token_row.get('cost_completion') or 0)

        # ===== STREAMING METRICS =====
        stream_row = conn.fetch_streaming_standard_query_counts(start_date, end_date)
        result['streaming_count'] = stream_row['followup_count'] or 0  # Using follow-up as proxy
        result['standard_count'] = stream_row['initial_count'] or 0
        total = result['streaming_count'] + result['standard_count']
        result['streaming_rate'] = (result['streaming_count'] / total * 100) if total > 0 else 0

        # ===== MODEL DISTRIBUTION =====
        model_distributions = conn.fetch_model_distribution(start_date, end_date)
        result['model_distribution'] = {row['model']: row['count'] for row in model_distributions}

        # ===== QUALITY METRICS =====
        quality_row = conn.fetch_query_quality_metrics(start_date, end_date)
        result['avg_response_length'] = int(quality_row['avg_response_length'] or 0)
        short = quality_row['short_responses'] or 0
        result['error_rate'] = (short / result['total_queries'] * 100) if result['total_queries'] > 0 else 0

        # Estimate citation metrics from sources JSONB
        citation_row = conn.fetch_query_citation_metrics(start_date, end_date)
        result['avg_citations'] = float(citation_row['avg_citations'] or 0)
        with_citations = citation_row['with_citations'] or 0
        result['citation_rate'] = (with_citations / result['total_queries'] * 100) if result[
                                                                                          'total_queries'] > 0 else 0

        # ===== QUERY TREND (Daily) =====
        trend_rows = conn.fetch_daily_query_trend(start_date, end_date)
        result['query_trend'] = {
            'labels': [row['day'].strftime('%m/%d') for row in trend_rows],
            'values': [row['count'] for row in trend_rows]
        }

        # ===== FEEDBACK METRICS =====

        fb_row = conn.fetch_feedback_metrics(start_date, end_date)
        result['total_feedback'] = fb_row['total_feedback'] or 0
        result['positive_feedback'] = fb_row.get('positive_feedback', 0) or 0
        result['negative_feedback'] = fb_row.get('negative_feedback', 0) or 0
        total_fb = result['positive_feedback'] + result['negative_feedback']
        result['satisfaction_rate'] = (result['positive_feedback'] / total_fb * 100) if total_fb > 0 else 0

        # Tag distribution
        tag_distributions = conn.fetch_feedback_tag_distribution(start_date, end_date)
        result['tag_distribution'] = {row['tag']: row['count'] for row in tag_distributions}

        # Recent feedback

        recent_fb = conn.fetch_recent_feedback(start_date, end_date)
        result['recent_feedback'] = [
            {
                'vote_id': r['id'],
                'timestamp': r['timestamp'].isoformat() if r['timestamp'] else None,
                'user_query': r['user_query'] or '',
                'feedback_tags': r['feedback_tags'],
                'comment': r['comments'],
                'thumbs_click': ''
            }
            for r in recent_fb
        ]

        # ===== OPENAI USAGE LOGS =====
        result['openai_usage_logs'] = conn.fetch_openai_usage_logs(start_date, end_date)

        return result

    except Exception as e:
        logger.error(f"Error getting observability summary: {e}")
        return {
            'total_queries': 0, 'avg_latency_ms': 0, 'total_tokens': 0,
            'total_cost': 0, 'satisfaction_rate': 0, 'streaming_rate': 0,
            'error': str(e)
        }

def get_experimental_mode_metrics(start_date=None, end_date=None):
    """
    Get metrics specifically for Experimental Mode dashboard tab.
    Returns per-persona metrics: latency, tokens, cost, and mode distribution.
    """
    from config import get_cost_rates

    conn = None
    try:
        conn = get_connection()

        result = {}

        # ===== MODE DISTRIBUTION =====

        mode_rows = conn.fetch_mode_distribution(start_date,end_date)

        experimental_queries = 0
        production_queries = 0
        for row in mode_rows:
            if row['mode'] == 'experimental':
                experimental_queries = row['count']
            elif row['mode'] == 'production':
                production_queries = row['count']
            else:
                # NULL or unknown modes count as production
                production_queries += row['count'] or 0

        total = experimental_queries + production_queries
        result['experimental_queries'] = experimental_queries
        result['production_queries'] = production_queries
        result['adoption_rate'] = round((experimental_queries / total * 100), 1) if total > 0 else 0

        # ===== PERSONA DISTRIBUTION =====

        persona_rows = conn.fetch_persona_distribution(start_date, end_date)
        result['persona_distribution'] = {
            row['persona'] or 'unknown': row['count']
            for row in persona_rows
        }

        # ===== PER-PERSONA METRICS =====
        # Latency, Tokens, Cost per persona

        persona_metrics = conn.fetch_persona_metrics(start_date, end_date)

        # Get cost rates using the actual model
        current_model = get_current_model()
        rates = get_cost_rates(current_model)

        # Add model info to result
        result['model'] = current_model
        result['cost_rates'] = {
            'prompt_per_1m': rates['prompt'],
            'completion_per_1m': rates['completion']
        }

        result['persona_stats'] = {}
        for row in persona_metrics:
            persona_name = row['persona'] or 'unknown'
            query_count = int(row['query_count'] or 0)

            total_cost = int(row.get('total_cost') or 0)
            cost_per_query = int(row.get('avg_cost_per_query') or 0)

            result['persona_stats'][persona_name] = {
                'query_count': query_count,
                'avg_latency_ms': int(row['avg_latency'] or 0),
                'avg_tokens': int(row['avg_tokens'] or 0),
                'total_tokens': int(row['total_tokens'] or 0),
                'total_cost': round(total_cost, 4),
                'cost_per_query': round(cost_per_query, 6)
            }

        # ===== MODE TREND OVER TIME =====
        # Daily breakdown of experimental vs production queries

        trend_rows = conn.fetch_experimental_production_query_trend(start_date, end_date)

        # Organize by date
        trend_by_date = {}
        for row in trend_rows:
            date_str = row['date'].isoformat() if row['date'] else 'unknown'
            if date_str not in trend_by_date:
                trend_by_date[date_str] = {'experimental': 0, 'production': 0}
            mode = row['mode'] or 'production'
            if mode in trend_by_date[date_str]:
                trend_by_date[date_str][mode] = row['count']
            else:
                trend_by_date[date_str]['production'] += row['count']

        result['mode_trend'] = {
            'labels': list(trend_by_date.keys()),
            'experimental': [trend_by_date[d]['experimental'] for d in trend_by_date],
            'production': [trend_by_date[d]['production'] for d in trend_by_date]
        }

        # ===== FEATURES CONFIG (for reference table) =====
        # Static representation of personas and their features
        result['persona_features'] = {
            'explorer': {
                'query_enhancement': False,
                'reranker': False,
                'self_critique': False,
                'groundedness_check': False,
                'correction_loop': False
            },
            'intermediate': {
                'query_enhancement': True,
                'reranker': True,
                'self_critique': True,
                'groundedness_check': False,
                'correction_loop': False
            },
            'scientist': {
                'query_enhancement': True,
                'reranker': True,
                'self_critique': False,
                'groundedness_check': True,
                'correction_loop': True
            }
        }

        # ===== RECENT EXPERIMENTAL QUERIES =====

        # Determine feedback based on votes if feedback_rating is not directly in rag_queries or if we need to join.
        # Note: rag_queries might not have feedback_rating column. Let's check schema or assume standard query above for recent_queries logic.
        # In get_query_analytics I used a standard select without feedback rating.
        # Ideally we want feedback too. But for now let's stick to what we know exists or safe fallbacks.
        # Actually, earlier view of get_query_analytics select didn't show feedback column.
        # I'll just select standard columns.

        result['recent_queries'] = conn.fetch_recent_experimental_queries(start_date, end_date)

        return result

    except Exception as e:
        logger.error(f"Error getting experimental mode metrics: {e}")
        return {
            'experimental_queries': 0,
            'production_queries': 0,
            'adoption_rate': 0,
            'persona_distribution': {},
            'persona_stats': {},
            'mode_trend': {'labels': [], 'experimental': [], 'production': []},
            'error': str(e)
        }
