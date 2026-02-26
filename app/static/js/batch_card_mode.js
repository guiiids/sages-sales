/**
 * Batch Card Mode - Integration with RAGKA
 * 
 * This file integrates the card-based UI for Batch mode with the existing RAGKA backend.
 * It replaces the chat-based interaction for Batch mode with a three-step card UI.
 */

(function() {
  // Check if environment is compatible
  if (!isCompatible()) {
    console.warn('Batch Card Mode: Environment not compatible, module disabled');
    return;
  }
  
  // Initialize only when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }
  
  function isCompatible() {
    // Check for required features and global objects
    return typeof fetch === 'function' && 
           typeof window.unifiedDevEvalConfig === 'object';
  }
  
  function initialize() {
    console.log('Initializing Batch Card Mode...');
    
    // Create and inject the batch card UI container
    createBatchCardUI();
    
    // Add batch card mode button to the mode buttons container
    addBatchCardModeButton();
    
    console.log('Batch Card Mode: Successfully initialized');
  }
  
  // State management for batch card mode
  const batchCardState = {
    query: '',
    customPrompt: '',
    temperature: 0.3,
    topP: 1.0,
    maxTokens: 1000,
    runs: 4,
    currentStep: 1,
    results: null,
    isProcessing: false,
    isVisible: false
  };
  
  function createBatchCardUI() {
    // Create container for batch card UI
    const batchCardContainer = document.createElement('div');
    batchCardContainer.id = 'batch-card-container';
    batchCardContainer.className = 'fixed inset-0 bg-gray-100 z-50 hidden';
    batchCardContainer.style.overflowY = 'auto';
    
    // Set the HTML content for the batch card UI
    batchCardContainer.innerHTML = `
      <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <div class="flex items-center justify-between mb-8">
          <div class="flex items-center">
            <img class="h-10 w-auto" src="https://content.tst-34.aws.agilent.com/wp-content/uploads/2025/05/logo-spark-1.png" alt="Logo">
            <h1 class="text-2xl font-bold ml-4 text-gray-800">RAGKA - Batch Mode</h1>
          </div>
          <button id="batch-back-to-chat" class="px-4 py-2 bg-gray-200 text-gray-800 rounded hover:bg-gray-300">
            Back to Chat
          </button>
        </div>

        <!-- Progress Indicator -->
        <div class="w-full bg-gray-200 rounded-full h-2.5 mb-8">
          <div id="batch-progress-bar" class="bg-blue-600 h-2.5 rounded-full" style="width: 33%; transition: width 0.3s ease;"></div>
        </div>

        <!-- Cards Container -->
        <div class="flex flex-col lg:flex-row justify-center gap-6 mb-8">
          <!-- Card 1: Settings -->
          <div id="batch-card-1" class="bg-gray-800 rounded-3xl p-6 w-full max-w-md flex flex-col" style="transition: transform 0.5s ease, opacity 0.5s ease;">
            <h2 class="text-xl font-semibold mb-2 text-white"># Batch Mode</h2>
            <h3 class="text-2xl font-bold mb-4 text-white">1. Settings</h3>

            <label class="mb-2 block text-sm text-white">Query</label>
            <textarea id="batch-query" class="w-full h-20 p-2 rounded-md text-black resize-none mb-4" placeholder="Enter your query here..."></textarea>

            <label class="mb-2 block text-sm text-white">Custom Prompt</label>
            <textarea id="batch-custom-prompt" class="w-full h-28 p-2 rounded-md text-black resize-none mb-4" placeholder="Add custom instructions to the system prompt..."></textarea>

            <label class="block mb-1 text-white">Temperature: <span id="batch-temp-value">0.3</span></label>
            <input id="batch-temperature" type="range" min="0" max="2" step="0.1" value="0.3" class="w-full mb-4" />

            <label class="block mb-1 text-white">Top P: <span id="batch-top-p-value">1.0</span></label>
            <input id="batch-top-p" type="range" min="0" max="1" step="0.05" value="1.0" class="w-full mb-4" />

            <label class="block mb-1 text-white">Max. Tokens: <span id="batch-max-tokens-value">1000</span></label>
            <input id="batch-max-tokens" type="range" min="100" max="4000" step="100" value="1000" class="w-full mb-4" />

            <label class="block mb-1 text-white">No of Runs</label>
            <input id="batch-runs" type="number" value="4" min="1" max="20" class="w-16 px-2 py-1 rounded text-black mb-4" />

            <button id="batch-next-to-review" class="ml-auto mt-auto bg-black text-white w-10 h-10 flex items-center justify-center rounded-full hover:bg-gray-700">
              &gt;
            </button>
          </div>

          <!-- Card 2: Review -->
          <div id="batch-card-2" class="bg-gray-800 rounded-3xl p-6 w-full max-w-md flex flex-col hidden" style="transition: transform 0.5s ease, opacity 0.5s ease;">
            <h2 class="text-xl font-semibold mb-2 text-white"># Batch Mode</h2>
            <h3 class="text-2xl font-bold mb-4 text-white">2. Review</h3>

            <div class="text-sm mb-4 text-white">
              <p><strong>Query</strong><br>
              <span id="batch-review-query"></span></p>
            </div>

            <div class="text-sm mb-4 text-white">
              <p><strong>Custom Prompt</strong><br>
              <span id="batch-review-prompt"></span></p>
            </div>

            <div class="text-sm space-y-2 text-white">
              <p><strong>Temperature:</strong> <span id="batch-review-temperature">0.3</span></p>
              <p><strong>Top P:</strong> <span id="batch-review-top-p">1.0</span></p>
              <p><strong>Max. Tokens:</strong> <span id="batch-review-max-tokens">1000</span></p>
              <p><strong>No of Runs:</strong> <span id="batch-review-runs">4</span></p>
            </div>

            <div class="flex justify-between mt-auto">
              <button id="batch-back-to-settings" class="bg-gray-600 text-white w-10 h-10 flex items-center justify-center rounded-full hover:bg-gray-500">
                &lt;
              </button>
              <button id="batch-start-process" class="bg-black text-white w-10 h-10 flex items-center justify-center rounded-full hover:bg-gray-700">
                &gt;
              </button>
            </div>
          </div>

          <!-- Card 3: Results -->
          <div id="batch-card-3" class="bg-gray-800 rounded-3xl p-6 w-full max-w-md flex flex-col hidden" style="transition: transform 0.5s ease, opacity 0.5s ease;">
            <h2 class="text-xl font-semibold mb-2 text-white"># Batch Mode</h2>
            <h3 class="text-2xl font-bold mb-4 text-white">3. Results</h3>

            <div id="batch-loading-indicator" class="flex flex-col items-center justify-center py-8">
              <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-white"></div>
              <p class="text-white mt-4">Processing batch runs...</p>
              <p class="text-white text-sm mt-2">Run <span id="batch-current-run">0</span> of <span id="batch-total-runs">4</span></p>
            </div>

            <div id="batch-results-content" class="hidden">
              <div class="text-sm mb-4 text-white">
                <p><strong>Query</strong><br>
                <span id="batch-result-query"></span></p>
              </div>

              <div class="text-sm mb-4 text-white">
                <p class="font-bold mb-1">Analysis</p>
                <div id="batch-result-analysis" class="space-y-1">
                  <!-- Analysis content will be inserted here -->
                </div>
              </div>
              
              <!-- Individual Run Results Section -->
              <div id="batch-run-results" class="text-sm mb-4 text-white">
                <p class="font-bold mb-2">Individual Run Results:</p>
                <!-- Run results will be inserted here -->
              </div>

              <div class="text-sm mb-4 font-bold text-white">Suggestions</div>
              <div id="batch-result-suggestions" class="text-sm mb-4 text-white">
                <!-- Suggestions content will be inserted here -->
              </div>
            </div>

            <div class="mt-auto flex gap-3">
              <button id="batch-back-to-review" class="bg-gray-600 hover:bg-gray-500 text-white px-4 py-2 rounded flex items-center gap-2">
                Back
              </button>
              <button id="batch-export-results" class="bg-pink-600 hover:bg-pink-700 text-white px-4 py-2 rounded flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v16h16V4H4zm4 4h8m-4 4v4" />
                </svg>
                Export
              </button>
              <button id="batch-new-process" class="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded">
                New Batch
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
    
    // Append to body
    document.body.appendChild(batchCardContainer);
    
    // Set up event listeners after DOM is updated
    setupEventListeners();
  }
  
  function addBatchCardModeButton() {
    // Find the mode buttons container
    const modeButtonsContainer = document.getElementById('mode-buttons-container');
    if (!modeButtonsContainer) {
      console.error('Mode buttons container not found');
      return;
    }
    
    // Create batch card mode button
    const batchCardButton = document.createElement('button');
    batchCardButton.id = 'toggle-batch-card-mode-btn';
    batchCardButton.className = 'mode-button px-4 py-2 text-xs font-medium text-black bg-white dark:bg-black text-white border rounded hover:bg-blue-200 hover:underline focus:outline-none focus:underline focus:ring-red-400';
    batchCardButton.textContent = 'Batch Card Mode';
    
    // Add click event listener
    batchCardButton.addEventListener('click', toggleBatchCardMode);
    
    // Add to container
    modeButtonsContainer.appendChild(batchCardButton);
  }
  
  function toggleBatchCardMode() {
    const batchCardContainer = document.getElementById('batch-card-container');
    if (!batchCardContainer) return;
    
    // Toggle visibility
    batchCardState.isVisible = !batchCardState.isVisible;
    
    if (batchCardState.isVisible) {
      // Show batch card UI
      batchCardContainer.classList.remove('hidden');
      // Reset to first step
      goToStep(1);
    } else {
      // Hide batch card UI
      batchCardContainer.classList.add('hidden');
    }
    
    // Update button styling
    const batchCardButton = document.getElementById('toggle-batch-card-mode-btn');
    if (batchCardButton) {
      if (batchCardState.isVisible) {
        batchCardButton.classList.add('active', 'bg-blue-200');
      } else {
        batchCardButton.classList.remove('active', 'bg-blue-200');
      }
    }
  }
  
  function setupEventListeners() {
    // Input elements
    const temperatureInput = document.getElementById('batch-temperature');
    const topPInput = document.getElementById('batch-top-p');
    const maxTokensInput = document.getElementById('batch-max-tokens');
    const runsInput = document.getElementById('batch-runs');
    
    // Navigation buttons
    const nextToReviewBtn = document.getElementById('batch-next-to-review');
    const backToSettingsBtn = document.getElementById('batch-back-to-settings');
    const startBatchBtn = document.getElementById('batch-start-process');
    const backToReviewBtn = document.getElementById('batch-back-to-review');
    const exportResultsBtn = document.getElementById('batch-export-results');
    const newBatchBtn = document.getElementById('batch-new-process');
    const backToChatBtn = document.getElementById('batch-back-to-chat');
    
    // Display elements
    const tempValue = document.getElementById('batch-temp-value');
    const topPValue = document.getElementById('batch-top-p-value');
    const maxTokensValue = document.getElementById('batch-max-tokens-value');
    
    // Set up input change handlers
    if (temperatureInput) {
      temperatureInput.addEventListener('input', (e) => {
        batchCardState.temperature = parseFloat(e.target.value);
        if (tempValue) tempValue.textContent = batchCardState.temperature;
      });
    }
    
    if (topPInput) {
      topPInput.addEventListener('input', (e) => {
        batchCardState.topP = parseFloat(e.target.value);
        if (topPValue) topPValue.textContent = batchCardState.topP;
      });
    }
    
    if (maxTokensInput) {
      maxTokensInput.addEventListener('input', (e) => {
        batchCardState.maxTokens = parseInt(e.target.value);
        if (maxTokensValue) maxTokensValue.textContent = batchCardState.maxTokens;
      });
    }
    
    if (runsInput) {
      runsInput.addEventListener('input', (e) => {
        batchCardState.runs = parseInt(e.target.value);
      });
    }
    
    // Set up navigation handlers
    if (nextToReviewBtn) nextToReviewBtn.addEventListener('click', () => goToReview());
    if (backToSettingsBtn) backToSettingsBtn.addEventListener('click', () => goToStep(1));
    if (startBatchBtn) startBatchBtn.addEventListener('click', () => startBatchProcess());
    if (backToReviewBtn) backToReviewBtn.addEventListener('click', () => goToStep(2));
    if (newBatchBtn) newBatchBtn.addEventListener('click', () => goToStep(1));
    if (backToChatBtn) backToChatBtn.addEventListener('click', () => toggleBatchCardMode());
    if (exportResultsBtn) exportResultsBtn.addEventListener('click', () => exportResults());
  }
  
  function goToStep(step) {
    batchCardState.currentStep = step;
    updateCardVisibility();
    
    // Update progress bar
    const progressBar = document.getElementById('batch-progress-bar');
    if (progressBar) {
      progressBar.style.width = `${step * 33}%`;
    }
  }
  
  function goToReview() {
    // Get query input
    const queryInput = document.getElementById('batch-query');
    const customPromptInput = document.getElementById('batch-custom-prompt');
    
    // Validate query
    if (!queryInput || !queryInput.value.trim()) {
      alert('Please enter a query before proceeding.');
      return;
    }
    
    // Update state
    batchCardState.query = queryInput.value.trim();
    batchCardState.customPrompt = customPromptInput ? customPromptInput.value.trim() : '';
    
    // Update review card
    const reviewQuery = document.getElementById('batch-review-query');
    const reviewPrompt = document.getElementById('batch-review-prompt');
    const reviewTemperature = document.getElementById('batch-review-temperature');
    const reviewTopP = document.getElementById('batch-review-top-p');
    const reviewMaxTokens = document.getElementById('batch-review-max-tokens');
    const reviewRuns = document.getElementById('batch-review-runs');
    
    if (reviewQuery) reviewQuery.textContent = batchCardState.query;
    if (reviewPrompt) reviewPrompt.textContent = batchCardState.customPrompt || '(Using default prompt)';
    if (reviewTemperature) reviewTemperature.textContent = batchCardState.temperature;
    if (reviewTopP) reviewTopP.textContent = batchCardState.topP;
    if (reviewMaxTokens) reviewMaxTokens.textContent = batchCardState.maxTokens;
    if (reviewRuns) reviewRuns.textContent = batchCardState.runs;
    
    // Go to step 2
    goToStep(2);
  }
  
  function updateCardVisibility() {
    // Get card elements
    const card1 = document.getElementById('batch-card-1');
    const card2 = document.getElementById('batch-card-2');
    const card3 = document.getElementById('batch-card-3');
    
    // Hide all cards first
    if (card1) {
      card1.classList.add('hidden');
      card1.style.opacity = '0.6';
      card1.style.transform = 'scale(0.95)';
    }
    if (card2) {
      card2.classList.add('hidden');
      card2.style.opacity = '0.6';
      card2.style.transform = 'scale(0.95)';
    }
    if (card3) {
      card3.classList.add('hidden');
      card3.style.opacity = '0.6';
      card3.style.transform = 'scale(0.95)';
    }
    
    // Show active card
    if (batchCardState.currentStep === 1 && card1) {
      card1.classList.remove('hidden');
      card1.style.opacity = '1';
      card1.style.transform = 'scale(1)';
    } else if (batchCardState.currentStep === 2 && card2) {
      card2.classList.remove('hidden');
      card2.style.opacity = '1';
      card2.style.transform = 'scale(1)';
    } else if (batchCardState.currentStep === 3 && card3) {
      card3.classList.remove('hidden');
      card3.style.opacity = '1';
      card3.style.transform = 'scale(1)';
    }
  }
  
  function startBatchProcess() {
    // Go to results step
    goToStep(3);
    batchCardState.isProcessing = true;
    
    // Show loading indicator, hide results content
    const loadingIndicator = document.getElementById('batch-loading-indicator');
    const resultsContent = document.getElementById('batch-results-content');
    
    if (loadingIndicator) loadingIndicator.classList.remove('hidden');
    if (resultsContent) resultsContent.classList.add('hidden');
    
    // Update run count display
    const totalRunsElement = document.getElementById('batch-total-runs');
    if (totalRunsElement) totalRunsElement.textContent = batchCardState.runs;
    
    // Prepare API request
    const apiEndpoint = window.unifiedDevEvalConfig.apiEndpoints.batch;
    const requestData = {
      query: batchCardState.query,
      custom_prompt: batchCardState.customPrompt,
      temperature: batchCardState.temperature,
      top_p: batchCardState.topP,
      max_tokens: batchCardState.maxTokens,
      runs: batchCardState.runs
    };
    
    // Make API request
    fetch(apiEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(requestData)
    })
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
      }
      return response.json();
    })
    .then(data => {
      // Process successful response
      processBatchResults(data);
    })
    .catch(error => {
      console.error('Error in batch processing:', error);
      // Show error in results
      showErrorResults(error.message);
    });
    
    // For demo purposes, also simulate progress updates
    simulateProgressUpdates();
  }
  
  function simulateProgressUpdates() {
    let currentRun = 0;
    const currentRunElement = document.getElementById('batch-current-run');
    const totalRuns = batchCardState.runs;
    
    function updateProgress() {
      currentRun++;
      if (currentRunElement) currentRunElement.textContent = currentRun;
      
      if (currentRun < totalRuns) {
        setTimeout(updateProgress, 1000);
      }
    }
    
    setTimeout(updateProgress, 1000);
  }
  
  function processBatchResults(data) {
    // Hide loading indicator, show results content
    const loadingIndicator = document.getElementById('batch-loading-indicator');
    const resultsContent = document.getElementById('batch-results-content');
    
    if (loadingIndicator) loadingIndicator.classList.add('hidden');
    if (resultsContent) resultsContent.classList.remove('hidden');
    
    // Store results in state
    batchCardState.results = data;
    batchCardState.isProcessing = false;
    
    // Update result query
    const resultQuery = document.getElementById('batch-result-query');
    if (resultQuery) resultQuery.textContent = batchCardState.query;
    
    // Update analysis section
    const resultAnalysis = document.getElementById('batch-result-analysis');
    if (resultAnalysis && data.analysis) {
      resultAnalysis.innerHTML = '';
      
      // Create list items for each analysis point
      data.analysis.forEach(point => {
        const listItem = document.createElement('li');
        listItem.className = 'list-disc list-inside';
        listItem.textContent = point;
        resultAnalysis.appendChild(listItem);
      });
    }
    
    // Update individual run results section
    const runResultsSection = document.getElementById('batch-run-results');
    if (runResultsSection && data.runs) {
      runResultsSection.innerHTML = '<p class="font-bold mb-2">Individual Run Results:</p>';
      
      // Create accordion for each run
      data.runs.forEach((run, index) => {
        const runContainer = document.createElement('div');
        runContainer.className = 'mb-2 border border-gray-700 rounded';
        
        // Create header with toggle functionality
        const runHeader = document.createElement('div');
        runHeader.className = 'flex items-center justify-between cursor-pointer hover:bg-gray-700 p-2 rounded-t';
        runHeader.innerHTML = `
          <span>Run ${index + 1}</span>
          <svg class="h-4 w-4 transform transition-transform" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
          </svg>
        `;
        
        // Create content (initially hidden)
        const runContent = document.createElement('div');
        runContent.className = 'p-2 border-t border-gray-700 bg-gray-900 hidden';
        runContent.innerHTML = `<pre class="whitespace-pre-wrap text-xs overflow-auto max-h-40">${run.response || 'No response data'}</pre>`;
        
        // Add toggle functionality
        runHeader.addEventListener('click', () => {
          runContent.classList.toggle('hidden');
          const svg = runHeader.querySelector('svg');
          if (svg) {
            svg.classList.toggle('rotate-180');
          }
        });
        
        runContainer.appendChild(runHeader);
        runContainer.appendChild(runContent);
        runResultsSection.appendChild(runContainer);
      });
    }
    
    // Update suggestions section
    const resultSuggestions = document.getElementById('batch-result-suggestions');
    if (resultSuggestions && data.suggestions) {
      resultSuggestions.textContent = data.suggestions;
    }
  }
  
  function showErrorResults(errorMessage) {
    // Hide loading indicator, show results content
    const loadingIndicator = document.getElementById('batch-loading-indicator');
    const resultsContent = document.getElementById('batch-results-content');
    
    if (loadingIndicator) loadingIndicator.classList.add('hidden');
    if (resultsContent) resultsContent.classList.remove('hidden');
    
    // Update analysis section with error
    const resultAnalysis = document.getElementById('batch-result-analysis');
    if (resultAnalysis) {
      resultAnalysis.innerHTML = `<li class="list-disc list-inside text-red-500">Error: ${errorMessage}</li>`;
    }
    
    // Update suggestions section
    const resultSuggestions = document.getElementById('batch-result-suggestions');
    if (resultSuggestions) {
      resultSuggestions.textContent = 'Try again with different parameters or check the console for more details.';
    }
    
    batchCardState.isProcessing = false;
  }
  
  function exportResults() {
    if (!batchCardState.results) {
      alert('No results available to export.');
      return;
    }
    
    // Create a blob with the JSON results
    const resultsBlob = new Blob(
      [JSON.stringify(batchCardState.results, null, 2)], 
      {type: 'application/json'}
    );
    
    // Create download link
    const downloadLink = document.createElement('a');
    downloadLink.href = URL.createObjectURL(resultsBlob);
    downloadLink.download = `batch_results_${new Date().toISOString().slice(0,10)}.json`;
    
    // Trigger download
    document.body.appendChild(downloadLink);
    downloadLink.click();
    document.body.removeChild(downloadLink);
  }
  
  // For demo/testing purposes, add a function to simulate results
  function simulateBatchResults() {
    // Mock data for testing
    const mockData = {
      analysis: [
        'Consistent responses across all runs with 87% similarity',
        'Average response time: 2.3 seconds',
        'All responses correctly addressed the query context'
      ],
      suggestions: 'Consider lowering the temperature to 0.2 for more consistent results, or increasing to 0.5 for more creative variations.',
      runs: [
        { 
          response: "iLab is Agilent's innovation laboratory focused on developing cutting-edge solutions for scientific research and analysis. It serves as a collaborative space where scientists and engineers work on next-generation technologies."
        },
        {
          response: "iLab is Agilent Technologies' innovation center that focuses on developing new technologies and solutions for scientific research. It brings together multidisciplinary teams to solve complex analytical challenges."
        },
        {
          response: "iLab refers to Agilent's innovation laboratory where researchers and engineers collaborate on developing advanced analytical technologies and solutions for various scientific fields."
        },
        {
          response: "iLab is Agilent's research and innovation center dedicated to creating breakthrough technologies in analytical science. It functions as an incubator for new ideas and solutions."
        }
      ]
    };
    
    // Process the mock results
    processBatchResults(mockData);
  }
})();
