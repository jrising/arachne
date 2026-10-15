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

function addButtons(temprend, uid) {
    $(temprend).parent().append("[<span class=\"vote-icons up-vote\" data-link-id=\"" + uid + "\">👍</span><span class=\"vote-icons down-vote\" data-link-id=\"" + uid + "\">👎</span><span class=\"vote-icons recycle\" data-link-id=\"" + uid + "\">♻</span>]");
}

function endResponse(temp, temprend) {
    addButtons(temprend, "response-" + $('.appmessagediv').length);
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
                <div class="usermessagediv">
                        <div class="usermessage">
                            ${escapedinput}
                        </div>
                </div>
            </div>`
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
        while (true) {
            const {done, value} = await reader.read();
	    if (done) break;

	    buffer += decoder.decode(value, {stream: true});

	    let newline;
	    while ((newline = buffer.indexOf("\n")) >= 0) {
		const line = buffer.slice(0, newline).trim();
		buffer = buffer.slice(newline + 1);

		if (!line) continue;

		console.log(line)
		
		let event;
		try {
		    event = JSON.parse(line);
		} catch (err) {
		    console.error("Bad stream event:", line);
		    continue;
		}

		if (event.type === "delta") {
		    addToResponse(event.text || "", temp, temprend);
		} else if (event.type === "status") {
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

	endResponse(temp, temprend);
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
});

// Link voting
// Function to apply the shake effect to newly added vote icons
function applyShakeEffect() {
    $('.vote-icons.clickable').last().effect('shake', {distance: 5}, 300);
}

// Function to handle up/down-vote and make AJAX call
function voteUp() {
    $(this).effect('shake', {distance: 5}, 300);
    var linkId = $(this).closest('.vote-icons').data('link-id');
    let upperdiv = document.getElementById('pastmessages');
    $.get({
        url: '/vote-updown',
	data: { id: linkId, prob: 1, past_messages: document.getElementById('pastmessages').innerHTML },
	function (data) {
            // Handle successful up-vote
            console.log('Up-vote successful for link ID:', linkId);
        }}).fail(function() {
            // Handle errors
            console.error('Error occurred.');
        });
}

function voteDown() {
    $(this).effect('shake', {distance: 5}, 300);
    var linkId = $(this).closest('.vote-icons').data('link-id');
    let upperdiv = document.getElementById('pastmessages');
    $.get({
        url: '/vote-updown',
	data: { id: linkId, prob: 0, past_messages: document.getElementById('pastmessages').innerHTML },
	function (data) {
            // Handle successful up-vote
            console.log('Down-vote successful for link ID:', linkId);
        }}).fail(function() {
            // Handle errors
            console.error('Error occurred.');
        });
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
