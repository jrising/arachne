let speechRecognition = new webkitSpeechRecognition();
var cancelStream = false;

function populateVoiceList($select) {
    voices = window.speechSynthesis.getVoices().sort(function (a, b) {
	const aname = a.name.toUpperCase();
	const bname = b.name.toUpperCase();
	
	if (aname < bname) {
	    return -1;
	} else if (aname == bname) {
	    return 0;
	} else {
	    return +1;
	}
    });

    var name = $select.find(":selected").data('name');
    if (!name)
	name = "Martha";
    
    $select.empty();
    for (let i = 0; i < voices.length; i++) {
	text = `${voices[i].name} (${voices[i].lang})`;
	if (voices[i].default)
	    text += " -- DEFAULT";

	var $option = $("<option />").text(text).data({name: voices[i].name, voice: voices[i]})
	if (voices[i].name == name)
	    $option.attr('selected', 'selected');
	$select.append($option);
    }
}

function speak_ui(text, $select, pitch, rate, onend) {
    if (window.speechSynthesis.speaking) {
	console.error("speechSynthesis.speaking");
	return;
    }

    const utterThis = new SpeechSynthesisUtterance(text);

    var voice = $select.find(":selected").data("voice");
    utterThis.voice = voice;
    utterThis.pitch = pitch;
    utterThis.rate = rate;

    utterThis.onend = onend;

    window.speechSynthesis.speak(utterThis);
}

async function speakStream($render, reader, voice, pitch, rate) {
    const synth = window.speechSynthesis;
    const decoder = new TextDecoder();
    let buffer = '';
    const maxBufferLength = 100; // or any suitable length
    let speaking = false;

    var lastutterance = null;
    while (true) {
	if (cancelStream) {
	    cancelStream = false;
	    window.speechSynthesis.cancel();
	    return;
	}
	
        const { done, value } = await reader.read();
        
        if (done) {
            break;
        }

        const text = decoder.decode(value);

	$render.append(text);
	
        buffer += text;

        // Check if buffer size exceeds max limit or if a pause occurs after certain characters
        if (buffer.length >= maxBufferLength || buffer.endsWith('.') || buffer.endsWith('!') || buffer.endsWith('?')) {
            if (!speaking) {
                const utterance = new SpeechSynthesisUtterance(buffer);
                utterance.voice = voice;
                utterance.pitch = pitch;
                utterance.rate = rate;

                utterance.onstart = () => {
                    speaking = true;
                };

                utterance.onend = () => {
                    speaking = false;
                };

                synth.speak(utterance);
                buffer = ''; // Clear buffer after speaking

		lastutterance = utterance;
            }
        }

        // Optional delay to prevent overwhelming the synthesis engine
        await new Promise(resolve => setTimeout(resolve, 100)); // Adjust the delay based on performance
    }

    // Speak any remaining content in the buffer after the stream ends
    if (buffer.length > 0) {
        const utterance = new SpeechSynthesisUtterance(buffer);
        utterance.voice = voice;
        utterance.pitch = pitch;
        utterance.rate = rate;

        synth.speak(utterance);

	lastutterance = utterance;
    }

    if (speaking) {
	lastutterance.onend = startListening;
    } else {
	startListening();
    }
}

async function respond(text) {
    let upperdiv = document.getElementById('upperid')
    upperdiv.innerHTML += `<div class="message">
                <div class="usermessagediv">
                        <div class="usermessage">
                            ${text}
                        </div>
                </div>
            </div>`;

    var searchForm = document.getElementById('input-form');
    var formData = new FormData(searchForm);

    if (text == "summarize") {
	var response = await fetch('/completion_reader_summary', {
	    method: 'POST',
	    body: formData
	});
    } else if (text.startsWith("page ")) {
	match = text.match(/\d+/);
	formData.append('page', parseInt(match[0], 10));
	var response = await fetch('/completion_reader', {
	    method: 'POST',
	    body: formData
	});
    } else {
	var response = await fetch('/completion_reader', {
	    method: 'POST',
	    body: formData
	});
    }
    const reader = response.body.getReader();

    upperdiv.innerHTML += `<div class="message">
                <div class="appmessagediv">
                    <div class="appmessage"></div>
                </div>
            </div>`
    $render = $(upperdiv).find('.appmessage').last();
    
    var voice = $('#voice').find(":selected").data("voice");
    speakStream($render, reader, voice, $('#pitch').val(), $('#rate').val());
}

function startListening() {
    speechRecognition.start();
    $('#status').text("Listening.");
}

if ("webkitSpeechRecognition" in window) {
    $(function() {
	// Setup for note-taking
	speechRecognition.continuous = false;
	speechRecognition.interimResults = true;
	speechRecognition.lang = 'en-US';

	let final_transcript = "";
	$('#status').text("Waiting.");

	function stopSpeaking() {
	    cancelStream = true
	    window.speechSynthesis.cancel();
	    fetch('/stop-stream', { method: 'POST' }).then((response) =>
		{});
	    startListening();
	}

	function resetListening() {
	    final_transcript = "";
	    $("#final").html("");
	    $("#interim").html("");
	}

	document.body.onkeydown = function(e) {
	    if (e.key == " " || e.code == "Space" || e.keyCode == 32) {
		stopSpeaking();
	    }
	}

	document.body.onkeyup = function(e) {
	    $('#status').text("Waiting.");
	    speechRecognition.stop();
	}

	document.body.onclick = () => {
	    if ($('#status').text() == "Waiting.") {
		startListening();
	    } else {
		stopSpeaking();
	    }
	}

	speechRecognition.onstart = () => {
	    console.log("onstart");
	    $("#status").show();
	    $("#status").text("Listening.");
	};
    
	speechRecognition.onend = () => {
	    console.log("onend");
	    if (final_transcript == "") {
		startListening();
		return;
	    }

	    if (/notes?\s+/.test(final_transcript) || final_transcript == "document") {
		var searchForm = document.getElementById('input-form');
		var formData = new FormData(searchForm);
		formData.append('input_text', final_transcript);

		let upperdiv = document.getElementById('upperid')
		upperdiv.innerHTML += `<div class="message">
                <div class="usermessagediv">
                        <div class="usermessage">
                            ${final_transcript}
                        </div>
                </div>
            </div>`;

		if (final_transcript == "document") {
		    $.getJSON('/reader_document', {log_filename: $('#log_filename').val(),
						   document: $('#document').val()}, function(json) {
						       speak_ui(`The document has ${json.total} pages and the next page is ${json.nextpage}.`, $('#voice'), $('#pitch').val(), $('#rate').val(), startListening);
		    });
		} else {
		    fetch('/reader_note', {
			method: 'POST',
			body: formData
		    });
		}

		resetListening();
		startListening();
		return;
	    } else if (/^(next\s)?page(\splease)?$/.test(final_transcript) ||
		       /^summarize$/.test(final_transcript) ||
		       /^page\s+\d+(\splease)?$/.test(final_transcript)) {
		respond(final_transcript).then(textout => {
		    resetListening();
		    $('#status').text("Responding.");
		}).catch(error => console.error(error));
	    } else {
		resetListening();
		speak_ui("I didn't catch that.", $('#voice'), $('#pitch').val(), $('#rate').val(), startListening);
		return;
	    }

	};

	speechRecognition.onError = () => {
	    console.log("onerror");
	    if (event.error == 'no-speech') {
	        
	    }
	    $("#status").text(event.error);
	};

	speechRecognition.onresult = (event) => {
	    console.log("onresult");
	    // Create the interim transcript string locally because we don't want it to persist like final transcript
	    let interim_transcript = "";

	    // Loop through the results from the speech recognition object.
	    for (let i = event.resultIndex; i < event.results.length; i++) {
		// If the result item is Final, add it to Final Transcript, Else add it to Interim transcript
		if (event.results[i].isFinal) {
		    final_transcript = event.results[i][0].transcript;
		} else {
		    interim_transcript += event.results[i][0].transcript;
		}
	    }

	    // Set the Final franscript and Interim transcript
	    $("#final").html(final_transcript);
	    $("#interim").html(interim_transcript);
	};
    });
} else {
    $("#status").text("Speech Recognition Not Available");
    upgrade();
}

if ('mediaSession' in navigator) {
    navigator.mediaSession.setActionHandler('play', function() {
	respond("NEXT").then(textout => {
	    resetListening();
	    $('#status').text("Responding.");
	}).catch(error => console.error(error));
    });

    navigator.mediaSession.setActionHandler('pause', function() {
	speak_ui("I don't know how to go to pause yet.", $('#voice'), $('#pitch').val(), $('#rate').val(), startListening);
    });
    navigator.mediaSession.setActionHandler('previoustrack', function() {
	speak_ui("I don't know how to go to the previous page yet.", $('#voice'), $('#pitch').val(), $('#rate').val(), startListening);
    });
    
    navigator.mediaSession.setActionHandler('nexttrack', function() {
	stopSpeaking();
	respond("NEXT").then(textout => {
	    resetListening();
	    $('#status').text("Responding.");
	}).catch(error => console.error(error));
    });
}
