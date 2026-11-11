mathjaxTimeout = null;

const md = window.markdownit({
    html: true, // Enable HTML tags in the source
    linkify: true, // Auto-convert URLs to links
    breaks: true,      // Convert '\n' in paragraphs into <br/>
    typographer: true, // Enable some language-neutral replacements + quotes beautification
    highlight: function (str, lang) {
	if (lang && hljs.getLanguage(lang)) {
	    try {
		return hljs.highlight(str, { language: lang }).value;
	    } catch (__) {}
	}
	return ''; // Use the external default escaping
    },
});

function myrender(htmltext, outputdiv) {
    outputdiv.innerHTML = md.render(htmlDecode(htmltext));
    clearTimeout(mathjaxTimeout);
    mathjaxTimeout = setTimeout(() => {
        if (window.MathJax && window.MathJax.typesetPromise) {
            // Typeset only the newly appended content box asynchronously
            MathJax.typesetPromise([outputdiv]).catch((err) => console.log(err));
        } else {
	    console.log("Not loaded.");
	}
    }, 150);
}

function addToResponse(text, temp, temprend) {
    const atBottom = isAtBottom();
    temp.innerHTML += htmlEscape(text);
    myrender(temp.innerHTML, temprend);
    if (atBottom)
	scrollToBottom();
}

function endResponse(temp, temprend, responseId) {
    addButtons(temprend, responseId);
    temp.removeAttribute('id');
    temprend.removeAttribute('id');
}

// for scrolling messages
function isAtBottom() {
    var div = document.getElementById("upperid");
    return (div.scrollHeight - div.offsetHeight) - div.scrollTop < 1;
}
      
function scrollToBottom() {
    var div = document.getElementById("upperid");
    div.scrollTop = div.scrollHeight;
}

function stopStreaming(event) {
    fetch('/stop-stream', { method: 'POST' }).then((response) =>
	response.json()).then((data) => {
	    if (data.status === 'success') {
		console.log(data.message);
		addButtons(document.getElementById('temprend'), "response-" + $('.appmessagediv').length);
	    } });
    event.preventDefault();
}

function htmlDecode(input) {
    var doc = new DOMParser().parseFromString(input, "text/html");
    return doc.documentElement.textContent;
}

function htmlEscape(str) {
    return str
        .replace(/>/g, '&gt')   
        .replace(/</g, '&lt');
}

completion_route = "/completion";

async function asyncSubmit() {
    let userinput = document.getElementById('input_text').value;
    let upperdiv = document.getElementById('pastmessages');

    setThinking(true, "Sending…");
    document.getElementById("thinking-details").textContent = "";

    if (userinput != "") {
	escapedinput = htmlEscape(userinput);
	upperdiv.innerHTML += `<div class="message">
    <div class="usermessagediv flex items-center justify-between">
        <div class="usermessage">${escapedinput}</div>
        <span class="vote-icons copy-btn text-xs cursor-pointer ml-2 opacity-70 hover:opacity-100" title="Copy raw text">📋</span>
    </div>
            </div>`;
	scrollToBottom();
    }

    var formData = new FormData(searchForm);
    formData.append('input_text', userinput);
    formData.append('past_messages', document.getElementById('pastmessages').innerHTML);

    formData.append('history', $('#history').text());
    if ($('#context-text').val() != "") {
	formData.append('context', $('#context-text').val());
    }
    if ($('#menu-option').length > 0 && $('#menu-option').val() != "") {
	formData.append('menu-option', $('#menu-option').val());
    }

    try {
        const response = await fetch(completion_route, {
            method: 'POST',
            body: formData
        });
        const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";
	
	upperdiv.innerHTML += `<div class="message">
                <div class="appmessagediv">
                    <div class="appmessage" id="temp" style="display: none"></div>
                    <div class="mdrender" id="temprend"></div>
                </div>
            </div>`
	      
        let temp = document.getElementById('temp');
	let temprend = document.getElementById('temprend');
	let responseId = null;
	
        while (true) {
            const {done, value} = await reader.read();
	    if (done) break;

	    buffer += decoder.decode(value, {stream: true});

	    let newline;
	    while ((newline = buffer.indexOf("\n")) >= 0) {
		const line = buffer.slice(0, newline).trim();
		buffer = buffer.slice(newline + 1);

		if (!line) continue;

		let event;
		try {
		    event = JSON.parse(line);
		} catch (err) {
		    console.error("Bad stream event:", line);
		    continue;
		}

		if (event.type != "delta")
		    console.log(line);
		
		if (event.type === "delta") {
		    addToResponse(event.text || "", temp, temprend);
		} else if (event.type === "response_id") {
		    responseId = event.response_id;
		    temprend.closest(".appmessagediv")
			.setAttribute("data-response-id", responseId);
		} else if (event.type === "status") {
		    if (event.phase === "initialize") {
			responseId = event.message
			temprend.closest(".appmessagediv")
			    .setAttribute("data-response-id", responseId);
		    }
		    updateThinking(event);
		} else if (event.type === "done") {
		    setThinking(false);
		} else if (event.type === "error") {
		    updateThinking({
			phase: "error",
			message: event.message || "Error"
		    });
		    setThinking(false, "Error");
		}
	    }
	}

	endResponse(temp, temprend, responseId);
	setThinking(false);

    } catch (error) {
        console.error(error);
	setThinking(false);
    }
}
            
window.addEventListener('beforeunload', function (e) {
    // Cancel the event as stated by the standard.
    e.preventDefault();
    
    // Chrome requires returnValue to be set.
    e.returnValue = '';
    
    // Send a request to your Flask app here
    $.ajax({
        url: '/window_closed',
        type: 'POST'
    });
});

document.addEventListener('DOMContentLoaded', function () {
    textField = document.getElementById('input_text');
    textField.addEventListener('keydown', async function (event) {
        if (event.keyCode === 13 && !event.shiftKey) {
	    event.preventDefault();
	    asyncSubmit();
        }
    });
});

var searchForm = null;
var textField = null;
$(function() {
    scrollToBottom();
    document.querySelector("#interrupt").addEventListener("click", stopStreaming); 

    searchForm = document.getElementById('input-form');
    textField = document.getElementById('input_text');

    searchForm.addEventListener('submit', async function(event) {
	event.preventDefault();
	asyncSubmit();
    });

    // Delegated click handler for all copy buttons
    $('body').on('click', '.copy-btn', function() {
	copyMessageText(this);
    });

    // Render buttons for existing assistant messages on page reload
    $('.appmessagediv').each(function(i) {
	const $render = $(this).find('.mdrender');
	const respId = $(this).attr('data-response-id') || `response-history-${i}`;
	if (!$(this).find('.vote-icons').length) {
            addButtons($render[0], respId);
	}
    });

    // Add copy buttons for existing user messages
    $('.usermessagediv').each(function() {
	addUserCopyButton($(this));
    });
});

// Link voting
// Function to apply the shake effect to newly added vote icons
function applyShakeEffect() {
    $('.vote-icons.clickable').last().effect('shake', {distance: 5}, 300);
}

function recycle() {
    $(this).effect('shake', {distance: 5}, 300);
    let userinput = document.getElementById('input_text').value;
    if (userinput != "") {
	$(this).closest('.message').prev().remove();
    }
    $(this).closest('.message').remove();
    asyncSubmit();
}

function setThinking(on, label = "Thinking…") {
    const box = document.getElementById("thinking-status");
    const lab = document.getElementById("thinking-label");
    if (!box || !lab) return;

    lab.textContent = label;
    box.classList.toggle("hidden", !on);
}

function updateThinking(event) {
    setThinking(true, event.message || "Thinking…");

    const details = document.getElementById("thinking-details");
    if (!details) return;

    let line = `[${event.phase || event.type}] ${event.message || ""}`;
    if (event.plan) line += `\n${event.plan}`;
    if (event.code) line += `\n\n${event.code}`;
    if (!event.plan && !event.ocde) line += `\n${JSON.stringify(event, null, 2)}`;

    details.textContent += line + "\n\n";
}

// Copy button

// Copy raw text to clipboard with temporary visual feedback
async function copyMessageText(btn) {
    const $parent = $(btn).closest('.appmessagediv, .usermessagediv');
    // Assistant text lives in .appmessage; User text lives in .usermessage
    const rawText = $parent.find('.appmessage, .usermessage').text().trim();
    
    try {
        await navigator.clipboard.writeText(rawText);
        const originalText = $(btn).html();
        $(btn).html('✓');
        setTimeout(() => $(btn).html(originalText), 1200);
    } catch (err) {
        console.error('Failed to copy: ', err);
    }
}

// Update addButtons to include copy button for assistant messages
function addButtons(temprend, uid) {
    $(temprend).parent().append(
        `[<span class="vote-icons copy-btn" data-link-id="${uid}" title="Copy raw text">📋</span>` +
        `<span class="vote-icons up-vote" data-link-id="${uid}">👍</span>` +
        `<span class="vote-icons down-vote" data-link-id="${uid}">👎</span>` +
        `<span class="vote-icons recycle" data-link-id="${uid}">♻</span>]`
    );
}

// Helper to attach copy button to user message elements
function addUserCopyButton($usermessagediv) {
    if (!$usermessagediv.find('.copy-btn').length) {
        $usermessagediv.append('<span class="vote-icons copy-btn text-xs cursor-pointer ml-2 opacity-70 hover:opacity-100" title="Copy raw text">📋</span>');
    }
}
