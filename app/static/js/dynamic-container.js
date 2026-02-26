/**
 * Dynamic Container Module
 * Implements a right-side container that shows programmatically and takes 30% of the area
 * When shown, the main chat area compresses from 70% to 50% width
 *
 * Enhanced with URL decoding capabilities for source documents
 */

class DynamicContainer {
  constructor() {
    this.isVisible = false;
    this.container = null;
    this.chatContainer = null;
    this.init();

    // Log initialization if debug logger is available
    if (window.debugLogger) {
      window.debugLogger.log("Dynamic Container initialized", "system");
    }
  }

  init() {
    // Get the main chat container
    this.chatContainer = document.querySelector(".chat-container");
    if (!this.chatContainer) {
      console.error("Chat container not found");
      return;
    }

    // Create the dynamic container
    this.createDynamicContainer();

    // Add event listeners
    this.addEventListeners();

    // Add CSS for transitions
    this.addTransitionStyles();
  }

  createDynamicContainer() {
    // Create the dynamic container element
    this.container = document.createElement("div");
    this.container.id = "dynamic-container";
    this.container.className = "dynamic-container hidden";

    // Create the container structure
    this.container.innerHTML = `
      <div class="dynamic-container-header">
        <button id="dynamic-container-close" class="close-btn" aria-label="Close panel">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
          </svg>
          <span class="close-label">Back</span>
        </button>
        <h2 id="dynamic-container-title" class="text-md font-semibold text-gray-900">Dynamic Content</h2>
        <button id="dynamic-container-close-x" class="close-btn close-x" aria-label="Close">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>
      <div id="dynamic-container-content" class="dynamic-container-content">
        <!-- Content will be inserted here -->
      </div>
    `;

    // Insert the container after the chat container
    this.chatContainer.parentNode.insertBefore(
      this.container,
      this.chatContainer.nextSibling,
    );
  }

  addTransitionStyles() {
    // Add CSS styles for the dynamic container and transitions
    const style = document.createElement("style");
    style.textContent = `
      /* Dynamic container styles */
      .dynamic-container {
        position: fixed;
        top: 0;
        right: 0;
        width: 40%;
        height: 100vh;
        background: white;
        border-left: 2px solid #e5e7eb;
        box-shadow: -4px 0 6px -1px rgba(0, 0, 0, 0.1);
        transform: translateX(100%);
        transition: transform 0.3s ease-in-out;
        z-index: 9999;
        display: flex;
        flex-direction: column;
      }

      /* Dark mode: dynamic container */
      .dark .dynamic-container {
        background: #1f2937;
        border-left-color: #374151;
        box-shadow: -4px 0 6px -1px rgba(0, 0, 0, 0.4);
      }

      .dynamic-container.visible {
        transform: translateX(0);
      }

      .dynamic-container-header {
        padding: 1rem;
        border-bottom: 1px solid #e5e7eb;
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #f9fafb;
        gap: 8px;
      }

      .dynamic-container-header .close-btn {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 6px 10px;
        border-radius: 8px;
        color: #6b7280;
        border: none;
        background: transparent;
        cursor: pointer;
        font-size: 14px;
        transition: all 0.2s;
      }

      .close-label {
        display: none;
      }

      /* On mobile: show Back label, hide the X button */
      @media (max-width: 768px) {
        .close-label {
          display: inline;
        }
        .close-x {
          display: none;
        }
      }

      /* On desktop: hide Back label, show the X button */
      @media (min-width: 769px) {
        #dynamic-container-close {
          display: none;
        }
        .close-x {
          display: flex;
        }
      }

      .close-btn:hover {
        color: #374151;
        background-color: #f3f4f6;
      }

      /* Dark mode: header */
      .dark .dynamic-container-header {
        background: #111827;
        border-bottom-color: #374151;
      }

      .dark .dynamic-container-header h2,
      .dark #dynamic-container-title {
        color: #e5e7eb;
      }

      .dynamic-container-content {
        flex: 1;
        padding: 1rem;
        overflow-y: auto;
      }

      /* Dark mode: content area text */
      .dark .dynamic-container-content {
        color: #e5e7eb;
      }

      .dark .dynamic-container-content h3,
      .dark .dynamic-container-content h4 {
        color: #f3f4f6;
      }

      .dark .dynamic-container-content p,
      .dark .dynamic-container-content strong {
        color: #d1d5db;
      }

      .dark .dynamic-container-content .bg-gray-50 {
        background: #374151 !important;
        color: #e5e7eb;
      }

      .dark .dynamic-container-content .text-gray-600,
      .dark .dynamic-container-content .text-gray-900 {
        color: #d1d5db !important;
      }

      /* Dark mode: close button */
      .dark .close-btn {
        color: #9ca3af;
      }

      .dark .close-btn:hover {
        color: #e5e7eb;
        background-color: #374151;
      }

      /* Chat container transitions */
      .chat-container {
        transition: width 0.3s ease-in-out, margin 0.3s ease-in-out;
      }

      .chat-container.compressed {
        width: 60% !important;
        margin-left: 0 !important;
        margin-right: auto !important;
      }

      /* Responsive adjustments */
      @media (max-width: 768px) {
        .dynamic-container {
          width: 100%;
        }
        
        .chat-container.compressed {
          width: 100% !important;
          margin: 0 auto !important;
        }
      }

      /* Hyperlink styles for triggering dynamic container */
      .dynamic-trigger {
        cursor: pointer;
        color: #2563eb;
        text-decoration: underline;
        transition: color 0.2s;
      }

      .dynamic-trigger:hover {
        color: #1d4ed8;
      }
      
    `;

    document.head.appendChild(style);
  }

  addEventListeners() {
    // Close button event listeners (both Back and X)
    document.addEventListener("click", (e) => {
      if (
        e.target.closest("#dynamic-container-close") ||
        e.target.closest("#dynamic-container-close-x")
      ) {
        this.hide();
      }
    });

    // Citation click: open dynamic container with source details
    document.addEventListener("click", (e) => {
      const citationLink = e.target.closest(".citation-link");
      if (citationLink) {
        e.preventDefault();
        this.handleCitationClick(citationLink);
        return;
      }
    });

    // Removed global <a[href]> listener to avoid breaking normal links,
    // only citation links and specifically marked triggers will be handled.

    // Click outside to close
    document.addEventListener("click", (e) => {
      if (
        this.isVisible &&
        this.container &&
        !this.container.contains(e.target)
      ) {
        // Check if the click is not on a citation link or any element that should trigger the container
        const isOnCitationLink = e.target.closest(".citation-link");
        const isOnTriggerLink =
          e.target.closest("a[href]") &&
          this.shouldTriggerDynamicContainer(e.target.closest("a[href]"));

        if (!isOnCitationLink && !isOnTriggerLink) {
          // Log the click-outside event if debug logger is available
          if (window.debugLogger) {
            window.debugLogger.log(
              "Click outside dynamic container detected",
              "user-action",
              {
                target: e.target.tagName,
                containerVisible: this.isVisible,
              },
            );
          }

          this.hide();
        }
      }
    });

    // Escape key to close
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.isVisible) {
        // Log the escape key press if debug logger is available
        if (window.debugLogger) {
          window.debugLogger.log(
            "Escape key pressed to close container",
            "user-action",
          );
        }

        this.hide();
      }
    });
  }

  shouldTriggerDynamicContainer(link) {
    // Do not trigger for citation links
    if (link.classList.contains("citation-link")) {
      return false;
    }
    // Check if the link should trigger the dynamic container
    const href = link.getAttribute("href");

    // Trigger for links with specific classes or data attributes
    if (
      link.classList.contains("dynamic-trigger") ||
      link.hasAttribute("data-dynamic-content")
    ) {
      return true;
    }

    return false;
  }

  handleLinkClick(link) {
    const href = link.getAttribute("href");
    const linkText = link.textContent;
    const dynamicContent = link.getAttribute("data-dynamic-content");

    let title = "Link Details";
    let content = "";

    if (dynamicContent) {
      // Use custom content if provided
      title = link.getAttribute("data-dynamic-title") || "Dynamic Content";
      content = dynamicContent;
    } else if (href && href.startsWith("http")) {
      // Handle external links
      title = "External Link";
      content = `
        <div class="space-y-4">
          <div>
            <h3 class="font-medium text-gray-900 mb-2">Link Information</h3>
            <p class="text-sm text-gray-600 mb-2"><strong>URL:</strong> <a href="${href}" target="_blank" class="text-blue-600 hover:underline">${href}</a></p>
            <p class="text-sm text-gray-600 mb-4"><strong>Text:</strong> ${linkText}</p>
          </div>
          <div class="border-t pt-4">
            <p class="text-sm text-gray-500 mb-3">This link leads to an external website. Choose an action:</p>
            <div class="space-y-2">
              <a href="${href}" target="_blank" class="w-full block px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors text-center">
                Open in New Tab
              </a>
              <button type="button" onclick="navigator.clipboard.writeText('${href}')" class="w-full px-4 py-2 bg-gray-200 text-gray-800 rounded hover:bg-gray-300 transition-colors">
                Copy URL
              </button>
            </div>
          </div>
        </div>
      `;
    }

    this.show(content, title);
  }

  removeAllHighlights() {
    document
      .querySelectorAll(".bg-yellow-100")
      .forEach((el) => el.classList.remove("bg-yellow-100"));
  }

  handleCitationClick(citationLink) {
    const sourceId = citationLink.getAttribute("data-source-id");

    // Log the citation click if debug logger is available
    if (window.debugLogger) {
      window.debugLogger.log(
        "Citation link clicked (dynamic mode)",
        "user-action",
        {
          sourceId: sourceId,
          linkText: citationLink.textContent,
          linkHref: citationLink.getAttribute("href"),
        },
      );
    }

    // Remove any existing highlights
    this.removeAllHighlights();

    // Get source information from the global lastSources
    if (window.lastSources && Array.isArray(window.lastSources)) {
      const sourceIndex = parseInt(sourceId) - 1;
      const source = window.lastSources[sourceIndex];

      if (source) {
        let title = `Source [${sourceId}]`;
        let content = "";

        if (typeof source === "string") {
          // Auto-link URLs in text-only source content
          const linkified = source.replace(
            /(?<!href=")(https?:\/\/[^\s<>"'()]+)/g,
            '<a href="$1" target="_blank" class="text-blue-600 underline">$1</a>',
          );
          content = `
            <div class="space-y-4">
              <div>
                <h3 class="font-medium text-gray-900 mb-2">Source Content</h3>
                <div class="bg-gray-50 p-3 rounded text-sm">
                  ${linkified}
                </div>
              </div>
            </div>
          `;
        } else if (typeof source === "object") {
          // Auto-link URLs in source.content
          const rawContent = source.content || "";
          const linkifiedContent = rawContent.replace(
            /(?<!href=")(https?:\/\/[^\s<>"'()]+)/g,
            '<a href="$1" target="_blank" class="text-blue-600 underline">$1</a>',
          );
          title = source.title || source.id || `Source [${sourceId}]`;

          // Build the content with source information
          content = `
            <div class="space-y-4" id="source-content">
              <div>
                <h3 class="font-medium text-gray-900 mb-2">Source Information</h3>
                ${source.title ? `<p class="text-sm text-gray-600 mb-2"><strong>Title:</strong> ${source.title}</p>` : ""}
                ${source.id ? `<p class="text-sm text-gray-600 mb-2"><strong>ID:</strong> ${source.id}</p>` : ""}
              </div>
              ${
                source.content
                  ? `
                <div>
                  <h4 class="font-medium text-gray-900 mb-2">Content</h4>
                  <div class="bg-gray-50 p-3 rounded text-sm leading-8 overflow-y-auto">
                 
                    ${linkifiedContent}
                  </div>
                </div>
              `
                  : ""
              }
          `;

          // Add download link if parent_id exists
          if (source.parent_id) {
            if (window.debugLogger) {
              window.debugLogger.log(
                "Source has parent_id, generating download link",
                "citation",
                {
                  sourceId: sourceId,
                  parentId: source.parent_id.substring(0, 30) + "...",
                },
              );
            }

            // Check if URL decoder is available
            if (window.urlDecoder) {
              const downloadLinkResult = this.createDownloadLink(
                source.parent_id,
              );
              content += downloadLinkResult.html;

              if (!downloadLinkResult.success) {
                if (window.debugLogger) {
                  window.debugLogger.log(
                    "Failed to create download link",
                    "error",
                    {
                      error: downloadLinkResult.error,
                    },
                  );
                }
              }
            } else {
              // Fallback if URL decoder is not available
              if (window.debugLogger) {
                window.debugLogger.log("URL decoder not available", "error");
              }

              content += `
                <div class="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-800">
                  <p><strong>Note:</strong> URL decoder module not loaded. Cannot generate download link.</p>
                </div>
              `;
            }
          } else {
            // No parent_id available
            if (window.debugLogger) {
              window.debugLogger.log(
                "Source missing parent_id, cannot generate download link",
                "warning",
              );
            }

            content += `
              <div class="mt-4 p-3 bg-gray-50 border border-gray-200 rounded text-sm text-gray-600">
                <p><strong>Note:</strong> No document link available for this source.</p>
              </div>
            `;
          }

          content += "</div>"; // Close the space-y-4 div
        }

        // Show the container with the source content
        this.show(content, title);
      } else {
        // Source not found
        if (window.debugLogger) {
          window.debugLogger.log("Source not found for citation", "error", {
            sourceId: sourceId,
            availableSources: window.lastSources.length,
          });
        }

        this.show(
          `
          <div class="p-4 bg-red-50 border border-red-200 rounded text-red-600">
            <p><strong>Error:</strong> Source information not found.</p>
          </div>
        `,
          `Source [${sourceId}] - Not Found`,
        );
      }
    } else {
      // No sources available
      if (window.debugLogger) {
        window.debugLogger.log("No sources available for citation", "error");
      }

      this.show(
        `
        <div class="p-4 bg-red-50 border border-red-200 rounded text-red-600">
          <p><strong>Error:</strong> No source information available.</p>
        </div>
      `,
        `Source [${sourceId}] - Not Available`,
      );
    }
  }

  show(content, title = "Dynamic Content") {
    if (!this.container) return;

    // Log the show action if debug logger is available
    if (window.debugLogger) {
      window.debugLogger.log("Showing dynamic container", "ui-state", {
        title: title,
        contentLength: content ? content.length : 0,
        contentType: typeof content,
      });
    }

    // Set the title and content
    const titleElement = document.getElementById("dynamic-container-title");
    const contentElement = document.getElementById("dynamic-container-content");

    if (titleElement) titleElement.textContent = title;
    if (contentElement) {
      contentElement.innerHTML = content;
      // Auto-link URLs in rendered HTML if not already linkified
      if (!contentElement.innerHTML.includes('<a href="')) {
        contentElement.innerHTML = contentElement.innerHTML.replace(
          /(?<!href=")(https?:\/\/[^\s<>"'()]+)/g,
          '<a href="$1" target="_blank" class="text-blue-600 underline">$1</a>',
        );
      }
    }

    // Show the container
    this.container.classList.remove("hidden");
    setTimeout(() => {
      this.container.classList.add("visible");
    }, 10);

    // Compress the chat container
    this.chatContainer.classList.add("compressed");

    // Add class to body to indicate dynamic container is open
    document.body.classList.add("dynamic-container-open");

    this.isVisible = true;
  }

  hide() {
    if (!this.container) return;

    // Log the hide action if debug logger is available
    if (window.debugLogger) {
      window.debugLogger.log("Hiding dynamic container", "ui-state", {
        wasVisible: this.isVisible,
        title: document.getElementById("dynamic-container-title")?.textContent,
      });
    }

    // Hide the container
    this.container.classList.remove("visible");

    // Restore the chat container
    this.chatContainer.classList.remove("compressed");

    // Remove class from body
    document.body.classList.remove("dynamic-container-open");

    setTimeout(() => {
      this.container.classList.add("hidden");
    }, 300);

    this.isVisible = false;
  }

  // Public API methods
  showContent(content, title) {
    this.show(content, title);
  }

  hideContainer() {
    this.hide();
  }

  isContainerVisible() {
    return this.isVisible;
  }
  createDownloadLink(base64Url) {
    if (!base64Url) {
      return {
        html: `
          <div class="mt-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-600">
            <p><strong>Error:</strong> No Base64 URL provided.</p>
          </div>
        `,
        success: false,
        error: "No Base64 URL provided",
      };
    }
    const downloadLink = "/api/download/" + base64Url;
    const viewLink = "/api/view/" + base64Url;
    // Return the HTML with both View Source (opens in-panel iframe) and Download buttons
    return {
      html: `
          <div class="mt-4 p-3 bg-green-50 border border-green-200 rounded text-sm">
            <h4 class="font-medium text-green-800 mb-2">Source Document Available</h4>
            <div class="mt-3 flex gap-2 flex-wrap">
                <a href="${viewLink}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center bg-blue-600 text-white font-semibold py-2 px-4 rounded-md hover:bg-blue-700 transition text-sm cursor-pointer border-0 no-underline">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                  View Source
                </a>
                <a href="${downloadLink}" target="_blank" class="inline-flex items-center bg-green-600 text-white font-semibold py-2 px-4 rounded-md hover:bg-green-700 transition text-sm download-source-link" data-dl-url="${downloadLink}">
                  <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download
                </a>
            </div>
          </div>
        `,
      success: true,
      error: null,
    };
  }

  showDocumentPreview(viewUrl, downloadUrl) {
    const content = `
      <div style="display:flex; flex-direction:column; height:100%; min-height:70vh;">
        <div style="margin-bottom:8px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
          <a href="${viewUrl}" target="_blank" rel="noopener noreferrer"
             class="inline-flex items-center text-sm text-blue-600 hover:text-blue-800 underline">
            Open in New Tab ↗
          </a>
          <a href="${downloadUrl}" target="_blank"
             class="inline-flex items-center text-sm text-green-600 hover:text-green-800 underline">
            Download ↓
          </a>
        </div>
        <iframe src="${viewUrl}" style="flex:1; width:100%; border:1px solid #e5e7eb; border-radius:8px; background:#fff; min-height:60vh;" allowfullscreen></iframe>
      </div>
    `;
    this.show(content, "Source Document");
  }
}

// Initialize the dynamic container when the DOM is loaded
document.addEventListener("DOMContentLoaded", () => {
  window.dynamicContainer = new DynamicContainer();
});

// Make the class available globally for external use
window.DynamicContainer = DynamicContainer;
