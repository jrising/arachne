async function sendText(text) {
    let upperdiv = document.getElementById('upperid')
    upperdiv.innerHTML += `<div class="message">
                <div class="usermessagediv">
                        <div class="usermessage">
                            ${text}
                        </div>
                </div>
            </div>`

    var searchForm = document.getElementById('input-form');
    var formData = new FormData(searchForm);
    formData.append('past_messages', upperdiv.innerHTML);
    formData.append('input_text', text);
    formData.append('preamble', 'austin');
    console.log(text);
    try {
	const response = await fetch('/completion_audio', {
            method: 'POST',
            body: formData
	});
	const reader = response.body.getReader();

	textout = ""
	while (true) {
            const {done, value} = await reader.read();
            const text = new TextDecoder().decode(value);
            if (done) {
		break
	    }
	    textout += text;
	}
	
	upperdiv.innerHTML += `<div class="message">
                <div class="appmessagediv">
                    <div class="appmessage">${textout}</div>
                </div>
            </div>`

	return textout;
    } catch (error) {
        console.error(error);
    }
}

/*let stopListeningAfterSilence = (() => {
    let silenceTimer = null;
    const silenceDuration = 3000; // duration in ms, adjust to fit

    return (recognition) => {
        clearTimeout(silenceTimer);
        silenceTimer = setTimeout(() => {
            recognition.stop();
        }, silenceDuration);
    }
})();*/

if ("webkitSpeechRecognition" in window) {
    $(function() {
	let speechRecognition = new webkitSpeechRecognition();
	// Setup for note-taking
	speechRecognition.continuous = true;
	speechRecognition.interimResults = true;
	speechRecognition.lang = 'en-US';

	let final_transcript = "";
	$('#status').text("Waiting.");

	function stopSpeaking() {
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

	speechRecognition.onstart = () => {
	    $("#status").show();
	    $("#status").text("Listening.");
	};
    
	speechRecognition.onend = () => {
	    if (final_transcript == "") {
		speechRecognition.start();
		return;
	    }
	    $("#status").text("Speaking...");

	    sendText(final_transcript).then(textout => {
		final_transcript = "";
		$("#final").html("");
		$("#interim").html("");
		$('#status').text("Waiting.");
	    }).catch(error => console.error(error));
	};

	speechRecognition.onError = () => {
	    if (event.error == 'no-speech') {
	        
	    }
	    $("#status").text(event.error);
	};

	speechRecognition.onresult = (event) => {
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
