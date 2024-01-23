function addToResponse(text, temp, temprend) {
   	const atBottom = isAtBottom();
    temp.innerHTML += htmlEscape(text);
	temprend.innerHTML = md.render(htmlDecode(temp.innerHTML));
	if (atBottom)
		scrollToBottom();
}

function endResponse(temp, temprend) {
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
		console.log(data.message); } });
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

const md = window.markdownit({
    html: true, // Enable HTML tags in the source
    linkify: true, // Auto-convert URLs to links
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

completion_route = "/completion";

async function asyncSubmit() {
    let userinput = document.getElementById('input_text').value
    let upperdiv = document.getElementById('upperid')
    
    upperdiv.innerHTML += `<div class="message">
                <div class="usermessagediv">
                        <div class="usermessage">
                            ${userinput}
                        </div>
                </div>
            </div>`
    scrollToBottom()

    var formData = new FormData(searchForm);
    formData.append('input_text', userinput);
    formData.append('past_messages', document.getElementById('upperid').innerHTML);

    formData.append('history', $('#history').text());
    if ($('#context-text').val() != "") {
	formData.append('context', $('#context-text').val());
    }

    try {
        const response = await fetch(completion_route, {
            method: 'POST',
            body: formData
        });
        const reader = response.body.getReader();
	
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
            const text = new TextDecoder().decode(value);
            if (done) {
                endResponse(temp, temprend);
		break;
	    }
            addToResponse(text, temp, temprend);
        }
    } catch (error) {
        console.error(error);
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
