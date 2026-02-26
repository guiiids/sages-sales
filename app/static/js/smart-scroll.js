/**
 * Smart Auto-Scroll Module
 * ========================
 * Prevents forced scrolling during streaming when the user has scrolled up.
 * 
 * Usage:
 *   window.smartScroll.init(chatMessages);        // Initialize on the chat container
 *   window.smartScroll.smart(chatMessages);        // Scroll only if near bottom (streaming)
 *   window.smartScroll.force(chatMessages);        // Always scroll (new message sent)
 */
(function () {
    const THRESHOLD = 80; // px from bottom to consider "at bottom"
    let userScrolledUp = false;

    function isNearBottom(el) {
        return (el.scrollHeight - el.scrollTop - el.clientHeight) < THRESHOLD;
    }

    function smartScrollToBottom(el) {
        if (!userScrolledUp || isNearBottom(el)) {
            el.scrollTop = el.scrollHeight;
        }
    }

    function forceScrollToBottom(el) {
        userScrolledUp = false;
        el.scrollTop = el.scrollHeight;
    }

    function initSmartScroll(el) {
        el.addEventListener('scroll', () => {
            if (isNearBottom(el)) {
                userScrolledUp = false;
            } else {
                userScrolledUp = true;
            }
        });
    }

    // Expose globally
    window.smartScroll = { init: initSmartScroll, smart: smartScrollToBottom, force: forceScrollToBottom };
})();
