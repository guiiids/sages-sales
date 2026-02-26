// Sage Dashboard JavaScript with API Integration and Modern UI Theme
class SageDashboard {
    constructor() {
        this.data = null;
        this.charts = {};
        this.apiBaseUrl = 'http://localhost:5001'; // Assuming backend runs here
        this.chartColors = {
            blueHues: ['#011f4b', '#03396c', '#005b96', '#6497b1', '#b3cde0'],
            breakdown: ['#011f4b', '#005b96']
        };
        this.ragLimit = 25;
        this.votesLimit = 25;
        this.initialDataUsed = false;
        this.init();
    }

    async init() {
        this.initializeDarkMode();
        this.showLoading();
        // Set default dates for the last 7 days
        this.setDefaultDates();
        await this.loadData();
        this.hideLoading();
    }

    setDefaultDates() {
        const endDateInput = document.getElementById('end-date');
        const startDateInput = document.getElementById('start-date');

        const end = new Date();
        const start = new Date();
        start.setDate(end.getDate() - 6); // Last 7 days including today

        // Format to YYYY-MM-DD
        const formatDate = (date) => date.toISOString().split('T')[0];

        endDateInput.value = formatDate(end);
        startDateInput.value = formatDate(start);
    }

    async loadData(startDate = null, endDate = null) {
        if (!startDate || !endDate) {
            startDate = document.getElementById('start-date').value;
            endDate = document.getElementById('end-date').value;
        }

        // Use pre-loaded data on first load if available
        if (!this.initialDataUsed && window.dashboardData &&
            (!startDate || startDate === document.getElementById('start-date').value)) {
            console.log('Using pre-loaded dashboard data');
            this.data = window.dashboardData;
            this.initialDataUsed = true;
            this.updateAllUIComponents();
            return;
        }

        try {
            let apiUrl = `${this.apiBaseUrl}/api/dashboard-data`;
            const params = new URLSearchParams();
            if (startDate) params.append('start_date', startDate);
            if (endDate) params.append('end_date', endDate);
            if (params.toString()) {
                apiUrl += '?' + params.toString();
            }

            const response = await fetch(apiUrl);
            if (!response.ok) throw new Error(`API request failed: ${response.status}`);

            this.data = await response.json();
            console.log('Data loaded from API:', this.data);
        } catch (error) {
            console.warn('Failed to load data from API, using sample data:', error);
            await this.delay(1000); // Simulate network delay
            this.data = this.getSampleData();
        } finally {
            this.updateAllUIComponents();
        }
    }

    getSampleData() {
        // This sample data will be shown if the backend is unreachable
        return {
            totalQueries: 16558, totalFeedback: 780, positiveFeedback: 234,
            constructiveFeedback: 546, feedbackWithComments: 234, feedbackRate: 4.7,
            positivePercentage: 30.0, constructiveCommentPercentage: 42.9,
            tagCounts: {
                'helpful': 234, 'Incorrect': 312, 'Incomplete': 89,
                'Data Source Quality': 67, 'Irrelevant': 45, 'Other Issue': 33, 'Hard to Understand': 0
            },
            dateRange: 'Sample Date Range - Past 7 Days', lastUpdated: new Date().toISOString(),
            status: 'sample', note: 'Sample data - API not available'
        };
    }

    updateAllUIComponents() {
        this.updateDateRange();
        this.updateMetrics();
        this.updateStatusIndicator();
        this.createOrUpdateCharts();
        this.updateInsights();
        // Load tables
        this.fetchRagQueries();
        this.fetchRecentFeedback();
    }

    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    updateDateRange() {
        const dateElement = document.getElementById('date-range');
        if (dateElement) {
            dateElement.textContent = this.data.dateRange || 'Date range not available';
        }
    }

    updateInsights() {
        document.getElementById('positive-feedback-count').textContent = this.data.positiveFeedback.toLocaleString();
        document.getElementById('constructive-feedback-count').textContent = this.data.constructiveFeedback.toLocaleString();
        document.getElementById('constructive-comment-percentage').textContent = `${this.data.constructiveCommentPercentage}%`;
    }

    updateMetrics() {
        this.animateValue('total-queries', this.data.totalQueries);
        this.animateValue('total-feedback', this.data.totalFeedback);
        this.animateValue('feedback-rate', this.data.feedbackRate, '%');
        this.animateValue('positive-percentage', this.data.positivePercentage, '%');

        // Update token and cost metrics
        // Check if token data is not available (dates before 2026-01-07)
        const totalTokensEl = document.getElementById('total-tokens');
        const tokenBreakdownEl = document.getElementById('token-breakdown');
        const totalCostEl = document.getElementById('total-cost');
        const costBreakdownEl = document.getElementById('cost-breakdown');

        const totalTokens = this.data.totalTokens || 0;
        const tokensPrompt = this.data.tokensPrompt || 0;
        const tokensCompletion = this.data.tokensCompletion || 0;
        const tokensCached = this.data.tokensCachedPrompt || 0;

        const totalCost = this.data.totalCostUSD || 0;
        const promptCost = this.data.promptCostUSD || 0;
        const completionCost = this.data.completionCostUSD || 0;
        const cachedCost = this.data.cachedPromptCostUSD || 0;

        // Update Total Tokens
        if (totalTokensEl) {
            totalTokensEl.textContent = totalTokens.toLocaleString();
        }

        // Update token breakdown
        if (tokenBreakdownEl) {
            tokenBreakdownEl.textContent = `${tokensPrompt.toLocaleString()} prompt • ${tokensCompletion.toLocaleString()} output • ${tokensCached.toLocaleString()} cached`;
        }

        // Update Total Cost
        if (totalCostEl) {
            totalCostEl.textContent = totalCost.toFixed(1);
        }

        // Update cost breakdown
        if (costBreakdownEl) {
            costBreakdownEl.textContent = `prompt $${promptCost.toFixed(2)} • output $${completionCost.toFixed(2)} • cached $${cachedCost.toFixed(2)}`;
        }
    }



    updateStatusIndicator() {
        const indicator = document.getElementById('status-indicator');
        if (!indicator) return;

        const content = indicator.querySelector('.status-content');
        const icon = indicator.querySelector('.status-icon');
        const text = indicator.querySelector('.status-text');

        content.className = 'status-content inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium'; // Reset classes

        switch (this.data.status) {
            case 'live':
                content.classList.add('bg-green-100', 'text-green-800', 'dark:bg-green-900/50', 'dark:text-green-300');
                icon.textContent = '●';
                text.textContent = `Live Data (Updated: ${new Date(this.data.lastUpdated).toLocaleTimeString()})`;
                break;
            case 'sample':
                content.classList.add('bg-amber-100', 'text-amber-800', 'dark:bg-amber-900/50', 'dark:text-amber-300');
                icon.textContent = '⚠';
                text.textContent = this.data.note || 'Displaying Sample Data';
                break;
            default:
                content.classList.add('bg-red-100', 'text-red-800', 'dark:bg-red-900/50', 'dark:text-red-300');
                icon.textContent = '✕';
                text.textContent = 'Error Loading Data';
        }
    }

    animateValue(elementId, endValue, suffix = '') {
        const element = document.getElementById(elementId);
        if (!element) return;

        let startValue = parseFloat(element.textContent.replace(/,/g, '')) || 0;
        const duration = 1500;
        const startTime = performance.now();

        const animate = (currentTime) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const easeOutQuart = 1 - Math.pow(1 - progress, 4);
            let currentValue = startValue + (endValue - startValue) * easeOutQuart;

            if (suffix === '%') {
                element.textContent = currentValue.toFixed(1) + suffix;
            } else {
                element.textContent = Math.floor(currentValue).toLocaleString();
            }

            if (progress < 1) requestAnimationFrame(animate);
        };

        requestAnimationFrame(animate);
    }

    createOrUpdateCharts() {
        this.createFeedbackBreakdownChart();
        this.createFeedbackTagsChart();
    }

    createFeedbackBreakdownChart() {
        const { positiveFeedback, constructiveFeedback } = this.data;
        const isDark = document.documentElement.classList.contains('dark');

        const options = {
            series: [positiveFeedback, constructiveFeedback],
            chart: { type: 'donut', height: '250px' },
            labels: ['Positive', 'Constructive'],
            colors: this.chartColors.breakdown,
            plotOptions: { pie: { donut: { size: '55%' } } },
            dataLabels: { enabled: true, formatter: (val) => val.toFixed(1) + '%', style: { colors: ['#FFFFFF'] } },
            legend: {
                position: 'bottom',
                horizontalAlign: 'center',
                fontSize: '14px',
                fontWeight: 400,
                markers: { width: 12, height: 12, radius: 2 },
                itemMargin: { horizontal: 16, vertical: 4 },
                labels: { colors: isDark ? '#9CA3AF' : '#6B7280' }
            },
            tooltip: { theme: isDark ? 'dark' : 'light' }
        };

        const ctx = document.getElementById('feedbackBreakdownChart');
        if (ctx) {
            if (this.charts.feedbackBreakdown) this.charts.feedbackBreakdown.destroy();
            this.charts.feedbackBreakdown = new ApexCharts(ctx, options);
            this.charts.feedbackBreakdown.render();
        }
    }

    createFeedbackTagsChart() {
        const constructiveTags = { ...this.data.tagCounts };
        delete constructiveTags.helpful; // Exclude 'helpful' from this chart
        const isDark = document.documentElement.classList.contains('dark');

        const sortedTags = Object.entries(constructiveTags)
            .filter(([, count]) => count > 0)
            .sort(([, a], [, b]) => b - a);

        const categories = sortedTags.map(([tag]) => tag);
        const data = sortedTags.map(([, count]) => count);

        const options = {
            series: [{ name: 'Count', data: data }],
            chart: { type: 'bar', height: '100%', toolbar: { show: false } },
            colors: this.chartColors.blueHues,
            fill: { type: 'solid' },
            plotOptions: { bar: { horizontal: true, borderRadius: 4, barHeight: '60%', distributed: true } },
            dataLabels: {
                enabled: true,
                textAnchor: 'start',
                style: { colors: ['#FFFFFF'], fontSize: '11px', fontWeight: 'bold' },
                offsetX: 5,
                formatter: (val) => val.toLocaleString()
            },
            xaxis: { categories: categories, labels: { style: { colors: isDark ? '#9CA3AF' : '#6B7280' } } },
            yaxis: { labels: { style: { fontSize: '12px', colors: isDark ? '#9CA3AF' : '#6B7280' } } },
            tooltip: { theme: isDark ? 'dark' : 'light' },
            grid: { borderColor: isDark ? '#374151' : '#E5E7EB' }
        };

        const ctx = document.getElementById('feedbackTagsChart');
        if (ctx) {
            if (this.charts.feedbackTags) this.charts.feedbackTags.destroy();
            this.charts.feedbackTags = new ApexCharts(ctx, options);
            this.charts.feedbackTags.render();
        }
    }

    showLoading() {
        document.getElementById('loading-overlay')?.classList.remove('hidden', 'opacity-0');
    }

    hideLoading() {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.classList.add('opacity-0');
            setTimeout(() => overlay.classList.add('hidden'), 300);
        }
    }

    async reloadWithFilters() {
        this.showLoading();
        await this.loadData();
        this.hideLoading();
    }

    async downloadReport() {
        const startDate = document.getElementById('start-date').value;
        const endDate = document.getElementById('end-date').value;
        let downloadUrl = `${this.apiBaseUrl}/api/download-excel`;

        const params = new URLSearchParams();
        if (startDate) params.append('start_date', startDate);
        if (endDate) params.append('end_date', endDate);
        if (params.toString()) {
            downloadUrl += '?' + params.toString();
        }

        window.location.href = downloadUrl;
    }

    // --- Dark Mode Logic ---
    toggleDarkMode() {
        const html = document.documentElement;
        html.classList.toggle('dark');
        localStorage.setItem('darkMode', html.classList.contains('dark'));
        this.updateDarkModeIcon();
        // Redraw charts with new theme colors
        this.createOrUpdateCharts();
    }

    updateDarkModeIcon() {
        const isDark = document.documentElement.classList.contains('dark');
        const icon = document.getElementById('dark-mode-icon');
        if (!icon) return;
        icon.innerHTML = isDark
            ? `<path stroke-linecap="round" stroke-linejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />` // Moon
            : `<path stroke-linecap="round" stroke-linejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />`; // Sun
    }

    initializeDarkMode() {
        if (localStorage.getItem('darkMode') === 'true' ||
            (!('darkMode' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
        this.updateDarkModeIcon();
    }

    // --- Table Logic ---

    async fetchRagQueries() {
        this.showTableLoading('rag');
        try {
            const startDate = document.getElementById('start-date').value;
            const endDate = document.getElementById('end-date').value;
            let url = `${this.apiBaseUrl}/api/rag_logs?limit=${this.ragLimit}`;
            if (startDate) url += `&start_date=${startDate}`;
            if (endDate) url += `&end_date=${endDate}`;

            const response = await fetch(url);
            if (!response.ok) throw new Error('Failed to fetch RAG logs');
            const data = await response.json();
            this.renderRagTable(data.logs || []);
        } catch (error) {
            console.error('Error fetching RAG queries:', error);
            this.renderTableError('rag');
        }
    }

    async fetchRecentFeedback() {
        this.showTableLoading('votes');
        try {
            const startDate = document.getElementById('start-date').value;
            const endDate = document.getElementById('end-date').value;
            // Note: api/recent-feedback might need date filters implementing server side if we want strict consistency
            // For now passing limit.
            let url = `${this.apiBaseUrl}/api/recent-feedback?limit=${this.votesLimit}`;

            const response = await fetch(url);
            if (!response.ok) throw new Error('Failed to fetch recent feedback');
            const data = await response.json();
            this.renderVotesTable(data || []);
        } catch (error) {
            console.error('Error fetching recent feedback:', error);
            this.renderTableError('votes');
        }
    }

    renderRagTable(logs) {
        const tbody = document.getElementById('ragTableBody');
        const emptyDiv = document.getElementById('ragEmpty');
        const loadingDiv = document.getElementById('ragLoading');

        if (loadingDiv) loadingDiv.classList.add('hidden');
        if (!tbody) return;
        tbody.innerHTML = '';

        if (!logs || logs.length === 0) {
            if (emptyDiv) emptyDiv.classList.remove('hidden');
            return;
        }
        if (emptyDiv) emptyDiv.classList.add('hidden');

        logs.forEach(log => {
            // Calculate cost logic (approximate if not provided)
            let cost = 0;
            if (log.prompt_tokens && log.completion_tokens) {
                // Using generic rates if not in DB, but DB log should have it?
                // Let's just show Total Tokens if cost is missing
            }
            // Format timestamp
            const date = new Date(log.timestamp);
            const timeStr = date.toLocaleString();

            const tr = document.createElement('tr');
            tr.className = 'hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors';
            tr.innerHTML = `
                <td class="px-3 py-2 whitespace-nowrap text-xs font-mono text-slate-500 dark:text-slate-400">#${log.id}</td>
                <td class="px-3 py-2 whitespace-nowrap text-xs text-slate-500 dark:text-slate-400" title="${timeStr}">${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
                <td class="px-3 py-2 text-xs text-slate-900 dark:text-white max-w-[200px] truncate" title="${this.escapeHtml(log.user_query)}">${this.escapeHtml(log.user_query)}</td>
                <td class="px-3 py-2 text-xs text-slate-500 dark:text-slate-400 max-w-[200px] truncate" title="${this.escapeHtml(log.response || '')}">${this.escapeHtml(log.response || '')}</td>
                <td class="px-3 py-2 text-xs text-slate-500 dark:text-slate-400 max-w-[150px] truncate">${this.escapeHtml(log.context || '')}</td>
                <td class="px-3 py-2 text-right text-xs font-mono text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-800/50 rounded">${log.total_tokens || '-'}</td>
                <td class="px-3 py-2 text-right text-xs font-mono text-slate-600 dark:text-slate-300">$${(0).toFixed(4)}</td>
                <td class="px-3 py-2 text-right text-xs font-mono ${this.getLatencyColor(log.llm_latency_ms)}">${log.llm_latency_ms || '-'}</td>
                <td class="px-3 py-2 text-right text-xs font-mono ${this.getLatencyColor(log.total_latency_ms)}">${log.total_latency_ms || '-'}</td>
                <td class="px-3 py-2 text-center text-xs text-slate-500">
                    <span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200">${(log.sources && log.sources.length) || 0}</span>
                </td>
                <td class="px-3 py-2 text-left text-xs text-slate-500 dark:text-slate-400">GPT-4</td>
                <td class="px-3 py-2 text-center text-xs">-</td>
                <td class="px-3 py-2 text-left text-xs text-slate-400 font-mono">...</td>
            `;
            tbody.appendChild(tr);
        });
    }

    renderVotesTable(votes) {
        const tbody = document.getElementById('votesTableBody');
        const emptyDiv = document.getElementById('votesEmpty');
        const loadingDiv = document.getElementById('votesLoading');

        if (loadingDiv) loadingDiv.classList.add('hidden');
        if (!tbody) return;
        tbody.innerHTML = '';

        if (!votes || votes.length === 0) {
            if (emptyDiv) emptyDiv.classList.remove('hidden');
            return;
        }
        if (emptyDiv) emptyDiv.classList.add('hidden');

        votes.forEach(vote => {
            const date = new Date(vote.timestamp);
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors';

            // Format tags
            let tagsHtml = '';
            if (vote.feedback_tags && Array.isArray(vote.feedback_tags)) {
                tagsHtml = vote.feedback_tags.map(tag =>
                    `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 mr-1">${this.escapeHtml(tag)}</span>`
                ).join('');
            }

            tr.innerHTML = `
                <td class="px-3 py-2 whitespace-nowrap text-xs font-mono text-slate-500 dark:text-slate-400">#${vote.vote_id}</td>
                <td class="px-3 py-2 whitespace-nowrap text-xs text-slate-500 dark:text-slate-400" title="${date.toLocaleString()}">${date.toLocaleDateString()}</td>
                <td class="px-3 py-2 text-xs text-slate-900 dark:text-white max-w-[200px] truncate" title="${this.escapeHtml(vote.user_query)}">${this.escapeHtml(vote.user_query)}</td>
                <td class="px-3 py-2 text-xs text-slate-500 dark:text-slate-400 max-w-[200px] truncate" title="${this.escapeHtml(vote.bot_response || '')}">${this.escapeHtml(vote.bot_response || '')}</td>
                <td class="px-3 py-2 text-left text-xs">${tagsHtml}</td>
                <td class="px-3 py-2 text-xs text-slate-600 dark:text-slate-300 max-w-[200px] truncate" title="${this.escapeHtml(vote.comment || '')}">${this.escapeHtml(vote.comment || '')}</td>
                <td class="px-3 py-2 text-left text-xs text-slate-400 font-mono">...</td>
            `;
            tbody.appendChild(tr);
        });
    }

    showTableLoading(type) {
        const loadingDiv = document.getElementById(`${type}Loading`);
        const emptyDiv = document.getElementById(`${type}Empty`);
        const tbody = document.getElementById(`${type}TableBody`);
        if (loadingDiv) loadingDiv.classList.remove('hidden');
        if (emptyDiv) emptyDiv.classList.add('hidden');
        if (tbody) tbody.innerHTML = '';
    }

    renderTableError(type) {
        const loadingDiv = document.getElementById(`${type}Loading`);
        if (loadingDiv) {
            loadingDiv.textContent = 'Error loading data';
            loadingDiv.classList.remove('hidden');
            loadingDiv.classList.add('text-red-500');
        }
    }

    getLatencyColor(ms) {
        if (!ms) return 'text-slate-400';
        if (ms < 1000) return 'text-green-600 dark:text-green-400';
        if (ms < 3000) return 'text-amber-600 dark:text-amber-400';
        return 'text-red-600 dark:text-red-400';
    }

    escapeHtml(unsafe) {
        if (!unsafe) return '';
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    setRagLimit(limit) {
        this.ragLimit = parseInt(limit);
        this.fetchRagQueries();
    }

    setVotesLimit(limit) {
        this.votesLimit = parseInt(limit);
        this.fetchRecentFeedback();
    }
}

// --- Global Scope for Button Clicks ---
let dashboard;

document.addEventListener('DOMContentLoaded', () => {
    dashboard = new SageDashboard();
});

function applyDateFilter() {
    if (dashboard) dashboard.reloadWithFilters();
}

function downloadReport() {
    if (dashboard) dashboard.downloadReport();
}

function toggleDarkMode() {
    if (dashboard) dashboard.toggleDarkMode();
}

function setRagLimit(limit) {
    if (dashboard) dashboard.setRagLimit(limit);
}

function setVotesLimit(limit) {
    if (dashboard) dashboard.setVotesLimit(limit);
}
