if ("webkitSpeechRecognition" in window) {
    $(function() {
	let speechRecognition = new webkitSpeechRecognition();
	// Setup for note-taking
	speechRecognition.continuous = true;
	speechRecognition.interimResults = true;
	speechRecognition.lang = 'en-US';

	let final_transcript = "";

	speechRecognition.onstart = () => {
	    $("#status").show();
	};
    
	speechRecognition.onend = () => {
	    $.ajax({
		url: 'save_notes',
		type: 'POST',
		data: { log_filename: $("#log_filename").html(), transcript: final_transcript }
	    });
	    $("#status").hide();
	};

	speechRecognition.onError = () => {
	    $("#status").hide();
	};

	speechRecognition.onresult = (event) => {
	    // Create the interim transcript string locally because we don't want it to persist like final transcript
	    let interim_transcript = "";

	    // Loop through the results from the speech recognition object.
	    for (let i = event.resultIndex; i < event.results.length; i++) {
		    // If the result item is Final, add it to Final Transcript, Else add it to Interim transcript
		    if (event.results[i].isFinal) {
		        final_transcript += (i) + event.results[i][0].transcript;
		    } else {
		        interim_transcript += (i) + event.results[i][0].transcript;
		    }
	    }

	    // Set the Final franscript and Interim transcript
	    $("#final").html(final_transcript);
	    $("#interim").html(interim_transcript);
	};

	speechRecognition.start();
    });
} else {
    console.log("Speech Recognition Not Available");
    upgrade();
}
