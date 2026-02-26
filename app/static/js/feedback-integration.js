/**
 * Enhanced Feedback Thumbs Integration Module
 * Integrates Font Awesome thumbs up/down feedback with horizontal layout,
 * reason checkboxes for negative feedback, comment box, and submit button.
 */
(function () {
    'use strict';

    // Configuration
    const FEEDBACK_CONFIG = {
        enabled: true,
        submitEndpoint: '/api/feedback',
        negativeReasons: [
            "Incorrect",
            "Incomplete",
            "Data Source Quality",
            "Irrelevant",
            "Hard to Understand",
            "Other Issue"
        ],
        // Positive flow options mirror the negative UI but capture time savings
        positiveReasons: [
            "No time saving",
            "1 to 15 mins",
            "16 to 30 mins",
            "31 to 60 mins",
            "> 60 mins",
            "Not specified"
        ]
    };

    // State management
    let messageCounter = 0;
    let feedbackSubmissions = new Set(); // Track submitted feedback by message ID

    function generateMessageId() {
        return `msg_${Date.now()}_${++messageCounter}`;
    }

    function createFeedbackHTML(messageId) {
        // build checkbox list for negative reasons
        const reasonsHTML = FEEDBACK_CONFIG.negativeReasons.map(reason =>
            `<label style="display:block; margin-bottom:4px;"><input type="checkbox" class="feedback-reason" value="${reason}"> ${reason}</label>`
        ).join('');

        return `
                <div class="feedback-container flex flex-wrap" data-message-id="${messageId}"
                    style="display: flex; flex-direction: column; align-items: flex-end; margin-left: 8px; font-size:14px; width: 100%;">
                    <div class="feedback-header flex items-center justify-end gap-2 pt-5" style="width: 100%;">
                        <span class="text-xs font-normal text-gray-500 dark:text-white/60">Was this helpful?</span>
                        <div class="feedback-icons inline-flex items-center gap-2">
                            <button type="button" class="copy-btn" title="Copy response" aria-label="Copy response" style="display:inline-flex;align-items:center;justify-content:center;border:none;color:#444;border-radius:6px;padding:4px;cursor:pointer;background:transparent;">
                                <i class="fa-solid fa-copy" aria-hidden="true" style="color: rgb(107, 114, 128);font-size:16px;"></i>
                            </button>
                            <div style="display: flex; align-items: center;">
                                <span class="copy-feedback" style="font-size:12px;color:#2f8f4e;display:none;margin-right:4px;">Copied!</span>
                                <i class="fa-solid fa-thumbs-up feedback-thumb" data-type="up"
                                style="color: #6b7280; cursor: pointer; margin-right: 8px; font-size: 16px; transition: color 0.2s;"
                                title="Was this helpful?"></i>
                                <i class="fa-solid fa-thumbs-down feedback-thumb" data-type="down"
                                style="color: #6b7280; cursor: pointer; font-size: 16px; transition: color 0.2s;"
                                title="Was this helpful?"></i>
                            </div>
                        </div>
                    </div>
                    <div class="feedback-details" style="display: none; margin-top: 5px; text-align: left; width: 350px;">
                        <fieldset class="dark:text-[#e0e0e0]/70" style="border:1px solid #ddd; padding:8px; border-radius:4px; margin-bottom:8px;">
                            <legend style="font-size:12px; margin-bottom:4px;">Select issues:</legend>
                            <div class="reasons-container">${reasonsHTML}</div>
                        </fieldset>
                        <div class="comment-container" style="display:none; margin-bottom:8px;">
                            <textarea class="feedback-comment text-gray-800 dark:bg-[#191919] dark:text-[#e0e0e0]"
                                    placeholder="Additional comments..."
                                    style="width:100%; box-sizing: border-box; height:60px; padding:4px; font-size:12px;border:1px solid #ddd;"></textarea>
                        </div>
                        <div class="feedback-actions" style="display: flex; gap: 8px; justify-content: flex-end; align-items: center; margin-top: 5px; margin-bottom: 5px;">
                            <button class="feedback-cancel-btn"
                                    style="display: none; background: #6b7280; color: white; border: none;
                                        padding: 4px 8px; border-radius: 4px; font-size: 12px; cursor: pointer;">
                                Cancel
                            </button>
                            <button class="feedback-submit-btn"
                                    style="display: none; background: #3b82f6; color: white; border: none;
                                        padding: 4px 8px; border-radius: 4px; font-size: 12px; cursor: pointer;">
                                Submit
                            </button>
                        </div>
                    </div>
                </div>
            `;
    }

    function handleThumbsUp(messageId, _) {
        if (feedbackSubmissions.has(messageId)) return;

        const container = document.querySelector(`[data-message-id="${messageId}"]`);

        // Reset any previous selection
        resetFeedbackState(container);

        // Set thumbs up as selected (persist green)
        container.querySelector('[data-type="up"]').style.color = '#22c55e';
        container.querySelector('[data-type="down"]').style.color = '#6b7280';

        // Populate positive reasons and show details
        const legend = container.querySelector('.feedback-details legend');
        if (legend) legend.innerHTML = 'Estimated time savings:';
        const reasonsContainer = container.querySelector('.reasons-container');
        if (reasonsContainer) {
            reasonsContainer.innerHTML = FEEDBACK_CONFIG.positiveReasons.map(reason =>
                `<label style="display:block; margin-bottom:4px;"><input type="radio" name="feedback_reason_${messageId}" class="feedback-reason" value="${reason}"> ${reason}</label>`
            ).join('');
            // Layout: horizontal grid, max 3 items per line
            reasonsContainer.style.display = 'grid';
            reasonsContainer.style.gridTemplateColumns = 'repeat(3, minmax(0, 1fr))';
            reasonsContainer.style.columnGap = '8px';
            reasonsContainer.style.rowGap = '6px';
        }
        // Show all fields at once
        container.querySelector('.feedback-details').style.display = 'block';
        container.querySelector('.comment-container').style.display = 'block';
        const submitBtn = container.querySelector('.feedback-submit-btn');
        if (submitBtn) submitBtn.style.display = 'inline-block';
        const cancelBtn = container.querySelector('.feedback-cancel-btn');
        if (cancelBtn) cancelBtn.style.display = 'inline-block';

        container.dataset.selectedType = 'positive';
    }

    function handleThumbsDown(messageId, _) {
        if (feedbackSubmissions.has(messageId)) return;

        const container = document.querySelector(`[data-message-id="${messageId}"]`);

        // Reset any previous selection
        resetFeedbackState(container);

        // Set thumbs down as selected (persist red)
        container.querySelector('[data-type="down"]').style.color = '#ef4444';
        container.querySelector('[data-type="up"]').style.color = '#6b7280';

        // Populate negative reasons and show details
        const legend = container.querySelector('.feedback-details legend');
        if (legend) legend.innerHTML = 'Select issues: <span style="color:#ef4444">*</span>';
        const reasonsContainer = container.querySelector('.reasons-container');
        if (reasonsContainer) {
            reasonsContainer.innerHTML = FEEDBACK_CONFIG.negativeReasons.map(reason =>
                `<label style="display:block; margin-bottom:4px;"><input type="checkbox" class="feedback-reason" value="${reason}"> ${reason}</label>`
            ).join('');
        }
        // Show all fields at once
        container.querySelector('.feedback-details').style.display = 'block';
        container.querySelector('.comment-container').style.display = 'block';
        const submitBtn = container.querySelector('.feedback-submit-btn');
        if (submitBtn) submitBtn.style.display = 'inline-block';
        const cancelBtn = container.querySelector('.feedback-cancel-btn');
        if (cancelBtn) cancelBtn.style.display = 'inline-block';
        container.dataset.selectedType = 'negative';
    }

    function resetFeedbackState(container) {
        // Reset all checkboxes
        container.querySelectorAll('.feedback-reason').forEach(cb => {
            cb.checked = false;
        });

        // Clear comment
        const commentBox = container.querySelector('.feedback-comment');
        if (commentBox) {
            commentBox.value = '';
        }

        // Hide details and action buttons
        container.querySelector('.feedback-details').style.display = 'none';
        container.querySelector('.comment-container').style.display = 'none';
        container.querySelector('.feedback-submit-btn').style.display = 'none';
        const cancelBtn = container.querySelector('.feedback-cancel-btn');
        if (cancelBtn) cancelBtn.style.display = 'none';

        // Reset selected type
        delete container.dataset.selectedType;
    }

    function handleSubmit(messageId,queryID) {
        if (feedbackSubmissions.has(messageId)) return;

        const container = document.querySelector(`[data-message-id="${messageId}"]`);
        const type = container.dataset.selectedType;
        if (!type) return;

        // gather tags and comment
        let tags = [];
        let comment = '';
        if (type === 'positive') {
            const checked = [...container.querySelectorAll('.feedback-reason')]
                .filter(cb => cb.checked)
                .map(cb => cb.value);
            // Default to "Not specified" if no time savings selected
            if (checked.length === 0) {
                checked.push('Not specified');
            }
            tags = ['helpful', ...checked];
            comment = container.querySelector('.feedback-comment').value.trim();
        } else {
            const checked = [...container.querySelectorAll('.feedback-reason')]
                .filter(cb => cb.checked)
                .map(cb => cb.value);
            if (checked.length === 0) {
                alert('Please select at least one issue.');
                return;
            }
            tags = checked;
            comment = container.querySelector('.feedback-comment').value.trim();
        }

        const feedbackData = {
            message_id: messageId,
            feedback_type: type,
            feedback_tags: tags,
            comment: comment,
            query_id: queryID,
            timestamp: new Date().toISOString()
        };

        submitFeedback(feedbackData, messageId);
    }

    function submitFeedback(feedbackData, messageId) {
        feedbackSubmissions.add(messageId);

        const botResponse = getMessageText(messageId);
        const userQuery = getUserQuery();
        const citations = getCitations(messageId);

        feedbackData.response = botResponse;
        feedbackData.question = userQuery;
        feedbackData.citations = citations;

        fetch(FEEDBACK_CONFIG.submitEndpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(feedbackData)
        })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showFeedbackConfirmation(messageId, 'Thank you for your feedback.');
                } else {
                    showFeedbackConfirmation(messageId, 'Error submitting feedback. Try again.');
                    feedbackSubmissions.delete(messageId);
                }
            })
            .catch(() => {
                showFeedbackConfirmation(messageId, 'Error submitting feedback. Try again.');
                feedbackSubmissions.delete(messageId);
            });
    }

    function showFeedbackConfirmation(messageId, msg) {
        const container = document.querySelector(`[data-message-id="${messageId}"]`);
        container.innerHTML = `<span style="color:#626362; font-size:12px;font-weight:bold;">${msg}</span>`;
    }

    function getCitations(messageId) {
        const container = document.querySelector(`[data-message-id="${messageId}"]`);
        const msgEl = container.closest('.bot-message');
        const citationEl = msgEl.querySelector('.citations-container');
        if (!citationEl) return [];

        const citations = Array.from(citationEl.querySelectorAll('.citation-item')).map(item => {
            const title = item.querySelector('.citation-title').textContent.trim();
            const url = item.querySelector('a').href;
            return { title, url };
        });
        return citations;
    }

    function getMessageText(messageId) {
        const container = document.querySelector(`[data-message-id="${messageId}"]`);
        const msgEl = container.closest('.bot-message');
        const txtEl = msgEl.querySelector('.message-bubble, .bot-bubble');
        return txtEl ? txtEl.textContent.trim() : '';
    }

    function getUserQuery() {
        // Try to find the most recent user message before the current bot message
        const messages = document.querySelectorAll('.user-message');
        if (messages.length === 0) return '';

        // Get the last user message
        const lastUserMsg = messages[messages.length - 1];
        const txtEl = lastUserMsg.querySelector('.message-bubble, .user-bubble');
        return txtEl ? txtEl.textContent.trim() : '';
    }

    function enhancedAddBotMessage(originalFn) {
        return function (message) {
            const result = originalFn.call(this, message);
            setTimeout(addFeedbackToLastMessage, 100);
            return result;
        };
    }

    function addFeedbackToLastMessage(queryID) {
        const bots = document.querySelectorAll('.bot-message');
        const last = bots[bots.length - 1];
        if (!last || last.querySelector('.feedback-container')) return;
        const text = last.textContent.toLowerCase();
        const skip = ['developer evaluation mode enabled', 'standard chat mode enabled',
            'processing evaluation', 'running developer evaluation'];
        if (skip.some(s => text.includes(s))) return;

        const containerDiv = last.querySelector('.flex.flex-col');
        if (!containerDiv) return;

        const msgId = generateMessageId();
        containerDiv.insertAdjacentHTML('beforeend', createFeedbackHTML(msgId));
        setupListeners(msgId, last,queryID);
    }

    function setupListeners(messageId, parent,queryID) {
        const container = parent.querySelector(`[data-message-id="${messageId}"]`);
        // Copy button handler
        const copyBtn = container.querySelector('.copy-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', async () => {
                const msgEl = container.closest('.bot-message');
                const contentDiv = msgEl && (msgEl.querySelector('.streaming-content') || msgEl.querySelector('.message-bubble'));
                const rawMarkdown = (msgEl && msgEl.dataset && msgEl.dataset.rawMarkdown) ? msgEl.dataset.rawMarkdown : '';
                const textToCopy = rawMarkdown || (contentDiv ? contentDiv.innerText.trim() : '');
                try {
                    if (typeof copyToClipboard === 'function') {
                        await copyToClipboard(textToCopy);
                    } else if (navigator.clipboard && window.isSecureContext) {
                        await navigator.clipboard.writeText(textToCopy);
                    } else {
                        const ta = document.createElement('textarea');
                        ta.value = textToCopy;
                        ta.style.position = 'fixed';
                        ta.style.top = '-10000px';
                        ta.style.left = '-10000px';
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand('copy');
                        document.body.removeChild(ta);
                    }
                    const fb = container.querySelector('.copy-feedback');
                    if (fb) {
                        fb.style.display = 'inline';
                        setTimeout(() => (fb.style.display = 'none'), 1200);
                    }
                } catch (e) {
                    console.error('Copy failed:', e);
                }
            });
        }
        container.querySelector('[data-type="up"]').addEventListener('click', () => {
            handleThumbsUp(messageId, getMessageText(messageId));
        });
        container.querySelector('[data-type="down"]').addEventListener('click', () => {
            handleThumbsDown(messageId, getMessageText(messageId));
        });
        container.querySelector('.feedback-submit-btn').addEventListener('click', () => {
            handleSubmit(messageId,queryID);
        });
        const cancelBtn = container.querySelector('.feedback-cancel-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                // Reset state and icon colors
                resetFeedbackState(container);
                const upEl = container.querySelector('[data-type="up"]');
                const downEl = container.querySelector('[data-type="down"]');
                if (upEl) upEl.style.color = '#6b7280';
                if (downEl) downEl.style.color = '#6b7280';
            });
        }
        // hover
        ['up', 'down'].forEach(type => {
            const el = container.querySelector(`[data-type="${type}"]`);
            const hoverColor = type === 'up' ? '#22c55e' : '#ef4444';
            const selectedColor = type === 'up' ? '#22c55e' : '#ef4444';

            el.addEventListener('mouseenter', () => {
                const sel = container.dataset.selectedType;
                const isSelected = (type === 'up' && sel === 'positive') || (type === 'down' && sel === 'negative');
                if (!isSelected) {
                    el.style.color = hoverColor;
                }
            });
            el.addEventListener('mouseleave', () => {
                const sel = container.dataset.selectedType;
                const isSelected = (type === 'up' && sel === 'positive') || (type === 'down' && sel === 'negative');
                el.style.color = isSelected ? selectedColor : '#6b7280';
            });
        });
    }

    function initializeFeedbackSystem() {
        if (!FEEDBACK_CONFIG.enabled) return;
        if (window.addBotMessage && typeof window.addBotMessage === 'function') {
            window.addBotMessage = enhancedAddBotMessage(window.addBotMessage);
            console.log('Feedback integration initialized');
        } else {
            console.warn('addBotMessage not found; feedback disabled');
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeFeedbackSystem);
    } else {
        initializeFeedbackSystem();
    }

    // Make key functions globally accessible
    window.addFeedbackToLastMessage = addFeedbackToLastMessage;

    window.FeedbackSystem = {
        config: FEEDBACK_CONFIG,
        feedbackSubmissions,
        addFeedbackToLastMessage: addFeedbackToLastMessage
    };
})();
