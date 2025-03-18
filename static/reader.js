let speechRecognition = new webkitSpeechRecognition();

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

function speak_ui(text, $select, pitch, rate) {
    if (window.speechSynthesis.speaking) {
	console.error("speechSynthesis.speaking");
	return;
    }

    const utterThis = new SpeechSynthesisUtterance(text);

    var voice = $select.find(":selected").data("voice");
    utterThis.voice = voice;
    utterThis.pitch = pitch;
    utterThis.rate = rate;

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
	lastutterance.onend = function(ev) {
	    speechRecognition.start();
	    $('#status').text("Listening.");
	}
    } else {
	speechRecognition.start();
	$('#status').text("Listening.");
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
    //formData.append('past_messages', upperdiv.innerHTML);
    //formData.append('input_text', text);
    
    const response = await fetch('/completion_reader', {
	method: 'POST',
	body: formData
    });
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

if ("webkitSpeechRecognition" in window) {
    $(function() {
	// Setup for note-taking
	speechRecognition.continuous = false;
	speechRecognition.interimResults = true;
	speechRecognition.lang = 'en-US';

	let final_transcript = "";
	$('#status').text("Waiting.");

	function stopSpeaking() {
	    window.speechSynthesis.cancel();
	    fetch('/stop-stream', { method: 'POST' }).then((response) =>
		{});
	}

	document.body.onkeydown = function(e) {
	    if (e.key == " " || e.code == "Space" || e.keyCode == 32) {
		if ($('#status').text() == "Speaking...") {
		    stopSpeaking();
		    $('#status').text("Waiting.");
		}
		if ($('#status').text() == "Waiting.") {
		    speechRecognition.start();
		    $('#status').text("Listening.");
		}
	    }
	}

	document.body.onkeyup = function(e) {
	    $('#status').text("Waiting.");
	    speechRecognition.stop();
	}

	document.body.onclick = () => {
	    if ($('#status').text() == "Waiting.") {
		speechRecognition.start();
		$('#status').text("Listening.");
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
		speechRecognition.start();
		$('#status').text("Listening.");
		return;
	    }

	    respond(final_transcript).then(textout => {
		final_transcript = "";
		$("#final").html("");
		$("#interim").html("");
		$('#status').text("Responding.");
	    }).catch(error => console.error(error));
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
