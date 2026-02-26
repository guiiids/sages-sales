document.addEventListener('DOMContentLoaded', () => {
    const promptSelect = document.getElementById('prompt-select');
    const initialQuestionInput = document.getElementById('initial-question');
    const followUpQuestionInput = document.getElementById('follow-up-question');
    const repetitionsInput = document.getElementById('repetitions');
    const startButton = document.getElementById('start-button');
    const saveButton = document.getElementById('save-button');
    const statusDiv = document.getElementById('status');
    const resultsLog = document.getElementById('results-log');

    let fullLogText = '';
    let prompts = [];

    // Fetch prompts on load
    fetch('/get_prompts')
        .then(response => response.json())
        .then(data => {
            prompts = data;
            populatePromptSelect(prompts);
        });

    promptSelect.addEventListener('change', (e) => {
        const selectedIndex = e.target.value;
        if (selectedIndex) {
            const selectedPrompt = prompts[selectedIndex];
            initialQuestionInput.value = selectedPrompt.prompt;
            followUpQuestionInput.value = selectedPrompt.follow_up_prompt;
        }
    });

    startButton.addEventListener('click', runAutomation);
    saveButton.addEventListener('click', saveLog);

    function populatePromptSelect(prompts) {
        promptSelect.innerHTML = '<option value="">Select a prompt...</option>';
        prompts.forEach((p, index) => {
            const option = document.createElement('option');
            option.value = index;
            option.textContent = `${p.category}: ${p.prompt.substring(0, 50)}...`;
            promptSelect.appendChild(option);
        });
    }

    async function runAutomation() {
        const initial_question = initialQuestionInput.value.trim();
        const follow_up_question = followUpQuestionInput.value.trim();
        const repetitions = parseInt(repetitionsInput.value, 10);

        if (!initial_question || !follow_up_question || repetitions < 1) {
            statusDiv.textContent = 'Please fill in all fields and specify at least 1 repetition.';
            return;
        }

        // Disable form and show progress
        setFormState(true);
        statusDiv.textContent = 'Running automation...';
        resultsLog.innerHTML = '';
        fullLogText = '';

        try {
            const response = await fetch('/run_automation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ initial_question, follow_up_question, repetitions }),
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.statusText}`);
            }

            const data = await response.json();
            displayResults(data.results);
            statusDiv.textContent = 'Automation complete.';
            saveButton.style.display = 'inline-block';

        } catch (error) {
            statusDiv.textContent = `Error: ${error.message}`;
            console.error('Automation failed:', error);
        } finally {
            setFormState(false);
        }
    }

    function displayResults(results) {
        results.forEach(cycle => {
            const cycleDiv = document.createElement('div');
            cycleDiv.className = 'cycle';

            let cycleText = `--- Cycle ${cycle.cycle} ---\n\n`;

            // Initial Question
            const iq = cycle.initial_question;
            cycleText += `Q1: ${iq.question}\n`;
            cycleText += `A1: ${iq.answer}\n`;
            cycleText += formatSources(iq.sources, 'S1');
            
            // Follow-up Question
            const fq = cycle.follow_up_question;
            cycleText += `\nQ2: ${fq.question}\n`;
            cycleText += `A2: ${fq.answer}\n`;
            cycleText += formatSources(fq.sources, 'S2');

            cycleDiv.textContent = cycleText;
            resultsLog.appendChild(cycleDiv);
            fullLogText += cycleText + '\n\n';
        });
    }

    function formatSources(sources, prefix) {
        if (!sources || sources.length === 0) {
            return `${prefix}: No sources cited.\n`;
        }
        let sourcesText = `${prefix}:\n`;
        sources.forEach(source => {
            sourcesText += `  - [${source.id}] ${source.title}\n`;
        });
        return sourcesText;
    }

    async function saveLog() {
        if (!fullLogText) {
            alert('No log to save.');
            return;
        }

        try {
            const response = await fetch('/save_conversation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conversation: fullLogText }),
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.statusText}`);
            }

            const data = await response.json();
            alert(data.message || 'Log saved successfully!');
            saveButton.disabled = true;

        } catch (error) {
            alert(`Failed to save log: ${error.message}`);
            console.error('Save failed:', error);
        }
    }

    function setFormState(isAutomationRunning) {
        startButton.disabled = isAutomationRunning;
        initialQuestionInput.disabled = isAutomationRunning;
        followUpQuestionInput.disabled = isAutomationRunning;
        repetitionsInput.disabled = isAutomationRunning;
    }
});
