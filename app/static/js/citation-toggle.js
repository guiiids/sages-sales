/**
 * Citation Toggle Module
 * Implements a toggle feature to switch between the old and new citation implementations
 */

(function() {
  // Configuration
  const STORAGE_KEY = 'useDynamicCitations';
  const DEFAULT_MODE = true; // Default to dynamic citation mode
  
  // Initialize the toggle state
  let useDynamicCitations = localStorage.getItem(STORAGE_KEY) === 'true' ? true : DEFAULT_MODE;
  
  // Create and add the toggle button to the UI
  function addToggleButton() {
    const modeButtonsContainer = document.getElementById('mode-buttons-container');
    if (!modeButtonsContainer) {
      console.error('Mode buttons container not found');
      return;
    }
    
    const toggleButton = document.createElement('button');
    toggleButton.id = 'toggle-dynamic-citations';
    toggleButton.className = 'mode-button px-4 py-2 text-xs font-medium text-black bg-white dark:bg-black text-white border rounded hover:bg-blue-200 hover:underline focus:outline-none focus:underline focus:ring-red-400';
    toggleButton.textContent = `Dynamic Citations: ${useDynamicCitations ? 'On' : 'Off'}`;
    
    modeButtonsContainer.appendChild(toggleButton);
    
    // Add click event listener
    toggleButton.addEventListener('click', toggleCitationMode);
  }
  
  // Toggle between citation modes
  function toggleCitationMode() {
    useDynamicCitations = !useDynamicCitations;
    
    // Update button text
    const toggleButton = document.getElementById('toggle-dynamic-citations');
    if (toggleButton) {
      toggleButton.textContent = `Dynamic Citations: ${useDynamicCitations ? 'On' : 'Off'}`;
    }
    
    // Save preference to localStorage
    localStorage.setItem(STORAGE_KEY, useDynamicCitations);
    
    // Log the change if debug logger is available
    if (window.debugLogger) {
      window.debugLogger.log(`Citation mode changed to: ${useDynamicCitations ? 'Dynamic' : 'Classic'}`, 'user-preference');
    }
    
    // Close any open citation panels
    if (window.dynamicContainer && window.dynamicContainer.isContainerVisible()) {
      window.dynamicContainer.hideContainer();
    }
    
    const sourcesContainer = document.getElementById('sources-container');
    if (sourcesContainer && !sourcesContainer.classList.contains('hidden')) {
      sourcesContainer.classList.add('hidden');
    }
  }
  
  // Override the citation click handler in the main template
  function overrideCitationClickHandler() {
    // Store the original handler
    const originalCitationHandler = window.handleCitationClick;
    
    // Create a new handler that checks the toggle state
    window.handleCitationClick = function(e) {
      const link = e.target.closest('.citation-link');
      if (!link) return;
      
      e.preventDefault();
      e.stopPropagation();
      
      // Get the source ID
      const sourceId = link.getAttribute('data-source-id');
      
      // Log the click if debug logger is available
      if (window.debugLogger) {
        window.debugLogger.log(`Citation link [${sourceId}] clicked`, 'user-action', {
          mode: useDynamicCitations ? 'Dynamic' : 'Classic'
        });
      }
      
      if (useDynamicCitations) {
        // Use the dynamic container implementation
        if (window.dynamicContainer) {
          // The dynamic container will handle the citation click
          const citationLink = e.target.closest('.citation-link');
          if (citationLink) {
            window.dynamicContainer.handleCitationClick(citationLink);
          }
        } else {
          console.error('Dynamic container not initialized');
        }
      } else {
        // Use the classic implementation
        // This code is based on the existing citation click handler in main.py
        const sourcesDiv = document.getElementById('sources');
        const sourcesBody = document.getElementById('sources-body');
        const sourcesContainer = document.getElementById('sources-container');
        const sourcesChevron = document.getElementById('sources-chevron');
        
        if (window.lastSources && Array.isArray(window.lastSources) && sourcesDiv) {
          sourcesDiv.innerHTML = '';
          window.lastSources.forEach((src, idx) => {
            const item = document.createElement('div');
            item.className = 'source-item mb-1 p-1 bg-gray-50 rounded text-sm';
            item.id = `source-${idx+1}`;
            let title = '', content = '';
            if (typeof src === 'string') {
              title = src.length > 100 ? src.substring(0,100) + '...' : src;
              content = src;
            } else {
              title = src.title || src.id || `Source ${idx+1}`;
              content = src.content || '';
            }
            const truncated = content.length > 150 ? content.substring(0,150) + '...' : content;
            item.innerHTML = `
              <h2 data-toc="true" id="source-${idx+1}"><a name="source-${idx+1}" class="text-sm text-black font-bold">[${idx+1}] ${title}</a></h2>
              <div class="source-content">${truncated}</div>
              ${content.length > 150 ? `<div class="source-full-content hidden">${content}</div><button class="toggle-source-btn text-blue-600 text-xs mt-1 hover:underline">Show more</button>` : ''}
            `;
            
            // Toggle handler
            const btn = item.querySelector('.toggle-source-btn');
            if (btn) {
              btn.addEventListener('click', function(ev) {
                ev.stopPropagation();
                const tr = item.querySelector('.source-content');
                const full = item.querySelector('.source-full-content');
                if (tr.classList.contains('hidden')) {
                  tr.classList.remove('hidden');
                  full.classList.add('hidden');
                  btn.textContent = 'Show more';
                } else {
                  tr.classList.add('hidden');
                  full.classList.remove('hidden');
                  btn.textContent = 'Show less';
                }
              });
            }
            sourcesDiv.appendChild(item);
          });
        }
        
        // Show panel and body expanded
        if (sourcesContainer) sourcesContainer.classList.remove('hidden');
        if (sourcesBody) sourcesBody.classList.remove('hidden');
        if (sourcesChevron) sourcesChevron.classList.remove('rotate-180');
        
        // Scroll to and highlight target source
        const target = document.getElementById(`source-${sourceId}`);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'center' });
          target.classList.add('bg-yellow-100');
          setTimeout(() => target.classList.remove('bg-yellow-100'), 2000);
        }
      }
    };
  }
  
  // Initialize the module
  function init() {
    // Make the toggle state available globally
    window.useDynamicCitations = useDynamicCitations;
    
    // Add the toggle button to the UI
    document.addEventListener('DOMContentLoaded', () => {
      addToggleButton();
      
      // Override the citation click handler
      overrideCitationClickHandler();
      
      // Log initialization if debug logger is available
      if (window.debugLogger) {
        window.debugLogger.log('Citation toggle initialized', 'system', {
          initialMode: useDynamicCitations ? 'Dynamic' : 'Classic'
        });
      }
    });
  }
  
  // Initialize the module
  init();
})();
