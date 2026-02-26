#app/routes/admin/admin_main_routes.py

#=====================================================================================================#
#Copyright (c) 2026 Agilent Technologies All rights reserved worldwide.
#Agilent Confidential, Use is permitted only in accordance with applicable End User License Agreement.
#=====================================================================================================#


import logging
from datetime import datetime, timedelta

from flask import Blueprint, render_template, g

from app.Connection import get_connection
from app.utils.admin_auth import admin_required
from app.utils.app_util import get_user_name

# Create a Blueprint for admin routes
admin_bp = Blueprint('admin', __name__)

logger = logging.getLogger(__name__)

@admin_bp.route('/')
@admin_required
def admin_index():
    user_name = get_user_name(g.user_info)
    dashboards = [
        {"title": "Observability", "description": "Centralized, graphical interface that visualizes real-time metrics", "link": "/admin/observability"},
        {"title": "Executive Overview", "description": "User level overview", "link": "/admin/executive-overview"},
        {"title": "Engagement Trends", "description": "12-Week Active User Growth & Engagement Metrics​", "link": "/admin/engagement-metrics"},
    ]
    return render_template('hub/admin_hub.html', dashboards=dashboards, user_name=user_name)

@admin_bp.route('/observability')
@admin_required
def admin_dashboard():
    """
    Admin dashboard route.
    Only accessible to users with admin privileges.
    Returns a welcome message for the secure dashboard.
    TODO: Implement actual dashboard functionality.
    """
    logger.info("Observability dashboard accessed")
    return render_template('hub/observability.html')

@admin_bp.route('/executive-overview')
@admin_required
def executive_overview_dashboard():
    return render_template('hub/user_executive_dashboard.html')

@admin_bp.route('/executive-overview-data')
@admin_required
def get_executive_overview_dashboard_data():
    now = datetime.now()
    start_90d = now - timedelta(days=90)
    start_30d = now - timedelta(days=30)
    start_prev_30d = now - timedelta(days=60)

    connection = get_connection()

    total_enabled_users = connection.get_users_count()
    active_users_90d = connection.get_active_users_count(start_90d, now)
    active_users_30d = connection.get_active_users_count(start_30d, now)
    active_users_prev_30d = connection.get_active_users_count(start_prev_30d, start_30d)

    total_queries_90d = connection.get_queries_count(start_90d, now)
    total_queries_30d = connection.get_queries_count(start_30d, now)
    total_queries_prev_30d = connection.get_queries_count(start_prev_30d, start_30d)

    # power users: more than 90% ile of daily users
    power_users = connection.get_user_sessions_percentile(90, 100, start_90d, now)
    power_users_pct = (power_users / total_enabled_users) * 100 if total_enabled_users > 0 else 0
    # regular users: between 60% ile and 90% ile of daily users
    regular_users = connection.get_user_sessions_percentile(60, 90, start_90d, now)
    regular_users_pct = (regular_users / total_enabled_users) * 100 if total_enabled_users > 0 else 0
    # occasional users: between 30% ile and 60% ile of daily users
    occasional_users = connection.get_user_sessions_percentile(30, 90, start_90d, now)
    occasional_users_pct = (occasional_users / total_enabled_users) * 100 if total_enabled_users > 0 else 0
    # inactive: less than 10% ile of daily users
    inactive_users = total_enabled_users - (power_users + regular_users + occasional_users)
    inactive_users_pct = (inactive_users / total_enabled_users) * 100 if total_enabled_users > 0 else 0

    sessions_per_week = connection.get_average_sessions_per_week(start_90d, now)
    messages_per_session = connection.get_average_messages_per_session(start_90d, now)
    queries_per_user = connection.get_average_queries_per_user(start_90d, now)
    # deep_mode_pct = connection.get_deep_mode_percentage(start_90d, now)
    deep_mode_pct = "NA"  # Placeholder value
    data = {
        "total_enabled_users": total_enabled_users,
        "active_users": active_users_90d,
        "active_users_pct": f"{(active_users_90d / total_enabled_users) * 100 if total_enabled_users > 0 else 0}%",
        "active_users_mom": f"{((active_users_30d - active_users_prev_30d) / active_users_prev_30d) * 100 if active_users_prev_30d > 0 else 100}%",
        "total_queries": total_queries_90d,
        "total_queries_mom": f"{((total_queries_30d - total_queries_prev_30d) / total_queries_prev_30d) * 100 if total_queries_prev_30d > 0 else 100}%",
        "adoption_tiers": [
            {"name": "Power Users", "actual": power_users_pct, "target": 40, "color": "#0057b8"},
            {"name": "Regular Users", "actual": regular_users_pct, "target": 20, "color": "#178a6b"},
            {"name": "Occasional Users", "actual": occasional_users_pct, "target": 20, "color": "#ffc300"},
            {"name": "Inactive", "actual": inactive_users_pct, "target": 20, "color": "#5a6473"},
        ],
        "metrics": [
            {"label": "Sessions/Week", "value": sessions_per_week, "color": "#d4f5e9"},
            {"label": "Msg/Session", "value": messages_per_session, "color": "#e3f0ff"},
            {"label": "Queries/User", "value": queries_per_user, "color": "#fff3e3"},
            {"label": "Deep Mode", "value": deep_mode_pct, "color": "#fff6e3"},
        ]
    }

    return data

@admin_bp.route('/engagement-metrics')
@admin_required
def admin_engagement_dashboard():
    return render_template('hub/admin_engagement_dashboard.html')

@admin_bp.route('/engagement-metrics-data')
@admin_required
def get_admin_engagement_dashboard_data():
    logger.info("Admin engagement dashboard accessed")
    connection = get_connection()

    now = datetime.now()
    end_week_start = now - timedelta(days=now.weekday())
    start_range = end_week_start - timedelta(weeks=11)
    end_range = end_week_start + timedelta(weeks=1)

    labels = [f"W{i + 1}" for i in range(12)]
    weekly_active_users = connection.get_weekly_active_user(start_range, end_range)
    weekly_queries = connection.get_weekly_queries(start_range, end_range)

    total_queries_12w = sum(weekly_queries)
    avg_queries_week = round(total_queries_12w / 12.0, 1) if total_queries_12w else 0
    avg_sessions_week = connection.get_average_sessions_per_week(start_range, end_range)
    avg_messages_session = connection.get_average_messages_per_session(start_range, end_range)

    prev_start = start_range - timedelta(weeks=12)
    prev_end = start_range
    prev_total_queries = connection.get_queries_count(prev_start, prev_end)
    prev_avg_queries_week = round(prev_total_queries / 12.0, 1) if prev_total_queries else 0
    prev_avg_sessions_week = connection.get_average_sessions_per_week(prev_start, prev_end)
    prev_avg_messages_session = connection.get_average_messages_per_session(prev_start, prev_end)

    def _diff(current, previous):
        if previous in (0, None):
            return None
        return round(current - previous, 1)

    data = {
        "labels": labels,
        "weekly_active_users": weekly_active_users,
        "weekly_queries": weekly_queries,
        "total_queries_week": avg_queries_week,
        "total_queries_week_diff": _diff(avg_queries_week, prev_avg_queries_week),
        "avg_sessions_week": avg_sessions_week,
        "avg_sessions_week_diff": _diff(avg_sessions_week, prev_avg_sessions_week),
        "avg_messages_session": avg_messages_session,
        "avg_messages_session_diff": _diff(avg_messages_session, prev_avg_messages_session),
        "deep_mode_adoption": "NA",
        "deep_mode_adoption_diff": "NA",
        "multi_turn_rate": "NA",
        "multi_turn_rate_diff": "NA",
    }

    return data

