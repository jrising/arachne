"use strict";

const state = {
    mode: null,
    peerConnection: null,
    dataChannel: null,
    localStream: null,
    liveEpoch: 0,
    liveConnecting: false,
    
    economyAbortController: null,

    messages: [],
    
    liveAssistantMessages: new Map(),
    liveUserMessages: new Map(),
    pendingLiveUserMessages: [],

    livePersistedUserItems: new Set(),
    livePersistedAssistantResponses: new Set(),

    mailQueue: [],
    mailCurrent: null,
    mailDraftThreadId: null,

    mailSpeechController: null,
    mailSpeechUtterance: null
};

Object.assign(state, {
  economyRecorder: null,
  economyAudioChunks: [],
  economyMicStream: null,
  economyRecording: false,
  speechVoice: null
});


const el = {
  status: document.getElementById("status"),
  transcript: document.getElementById("transcript"),
  emptyTranscript: document.getElementById("empty-transcript"),
  textForm: document.getElementById("text-form"),
  textInput: document.getElementById("text-input"),
  sendButton: document.getElementById("send-button"),
  liveConnectButton: document.getElementById("live-connect-button"),
  interruptButton: document.getElementById("interrupt-button"),
  agentAudio: document.getElementById("agent-audio"),
  modeButtons: document.querySelectorAll("[data-mode]"),
  readerDocument: document.getElementById("reader-document"),
    readerStatus: document.getElementById("reader-status"),

    mailNext: document.getElementById("mail-next"),
    mailArchive: document.getElementById("mail-archive"),
    mailDraft: document.getElementById("mail-draft"),
};

Object.assign(el, {
    economyMicButton: document.getElementById("economy-mic-button"),
    speechPreview: document.getElementById("speech-preview"),
    speechVoice: document.getElementById("speech-voice"),
    speechRate: document.getElementById("speech-rate"),
    speechPitch: document.getElementById("speech-pitch"),
    speechRateValue: document.getElementById("speech-rate-value"),
    speechPitchValue: document.getElementById("speech-pitch-value"),
    drivingOverlay: document.getElementById("driving-overlay"),
    drivingPrimary: document.getElementById("driving-primary"),
    drivingSecondary: document.getElementById("driving-secondary"),
    drivingClose: document.getElementById("driving-close"),
    drivingReopen: document.getElementById("driving-overlay-reopen"),
    drivingReaderDocument: document.getElementById("driving-reader-document")
});

function setStatus(text) {
  el.status.textContent = text;
}

function scrollTranscriptToBottom() {
  el.transcript.scrollTop = el.transcript.scrollHeight;
}

function addMessage(role, text = "", { partial = false } = {}) {
  el.emptyTranscript?.remove();

  const message = document.createElement("div");
  message.className = `message ${role}${partial ? " partial" : ""}`;
  message.textContent = text;

  el.transcript.appendChild(message);
  scrollTranscriptToBottom();
  return message;
}

function appendMessageText(message, text) {
  message.textContent += text;
  scrollTranscriptToBottom();
}

function finalizeMessage(message) {
  message.classList.remove("partial");
  scrollTranscriptToBottom();
}

function selectedDocument() {
  return el.drivingReaderDocument?.value || el.readerDocument?.value || "";
}

function setMode(mode) {
    if (state.mode === mode) return;

    // Economy must not leave an active microphone/Reatime session behind.
    if (mode === "economy" && state.peerConnection) {
	disconnectLive();
    }

    // Avoid a running Economy request continuing after entering Live.
    if (mode === "live") {
	stopEconomyRequest();
    }

    state.mode = mode;

    for (const button of el.modeButtons) {
	button.classList.toggle("active", button.dataset.mode === mode);
    }

    if (mode === "live") {
	el.liveConnectButton.hidden = false;
	el.textInput.placeholder = "Type a message, or connect to speak live…";
	setStatus("Connecting live voice…");
	void connectLive();
    } else {
	el.liveConnectButton.hidden = true;
	el.textInput.placeholder = "Type a message…";
	setStatus("Economy mode ready.");
    }
}

function stopEconomyRequest() {
  if (state.economyAbortController) {
    state.economyAbortController.abort();
    state.economyAbortController = null;
  }
}

function createPendingLiveUserMessage() {
  const message = addMessage("user", "…", { partial: true });
  state.pendingLiveUserMessages.push(message);
  return message;
}

function completePendingLiveUserMessage(transcript) {
  const message = state.pendingLiveUserMessages.shift()
    || addMessage("user", "", { partial: true });

  message.textContent = transcript || "[No speech recognized]";
  finalizeMessage(message);
  return message;
}

function disconnectLive() {
  // Invalidates callbacks from this and all prior Live sessions.
  state.liveEpoch += 1;
  state.liveConnecting = false;

  const dataChannel = state.dataChannel;
  const peerConnection = state.peerConnection;
  const localStream = state.localStream;

  state.dataChannel = null;
  state.peerConnection = null;
  state.localStream = null;

  if (dataChannel) dataChannel.close();
  if (peerConnection) peerConnection.close();

  for (const track of localStream?.getTracks() || []) {
    track.stop();
  }

  el.agentAudio.pause();
  el.agentAudio.srcObject = null;
  el.liveConnectButton.textContent = "Connect live voice";
  el.interruptButton.disabled = !state.economyAbortController;

  // These IDs are only meaningful within one Realtime session.
  state.liveAssistantMessages.clear();
  state.liveUserMessages.clear();
    state.pendingLiveUserMessages = [];

    state.livePersistedUserItems.clear();
    state.livePersistedAssistantResponses.clear();

}

function interruptEverything() {
  stopEconomyRecording();
  stopEconomyRequest();
  window.speechSynthesis?.cancel();
    stopMailPlayback();
    
  if (state.peerConnection) {
    disconnectLive();
  }

  setStatus("Stopped.");
}

async function connectLive() {
    if (state.liveConnecting) return;

    if (state.peerConnection) {
	disconnectLive();
	setStatus("Live voice disconnected.");
	return;
    }

    state.liveConnecting = true;
    const epoch = ++state.liveEpoch;

    try {
	setStatus("Requesting microphone access…");

	const params = new URLSearchParams({
	    log_filename: window.VOICE_CONFIG.log_filename,
	    profile_id: window.VOICE_CONFIG.profile_id
	});

	const secretResponse = await fetch(
	    `${window.VOICE_ENDPOINTS.realtimeSession}?${params}`
	);
	const secretData = await secretResponse.json();
	
	if (!secretResponse.ok || secretData.error) {
	    throw new Error(secretData.error || "Could not create Realtime session.");
	}
	
	const ephemeralToken = secretData.value;
	if (!ephemeralToken) {
	    throw new Error("Realtime session response did not contain a token.");
	}

	state.localStream = await navigator.mediaDevices.getUserMedia({
	    audio: {
		echoCancellation: true,
		noiseSuppression: true,
		autoGainControl: true
	    }
	});
	
	const pc = new RTCPeerConnection();
	state.peerConnection = pc;

	pc.onconnectionstatechange = () => {
	    if (epoch !== state.liveEpoch || state.peerConnection !== pc) return;

	    if (pc.connectionState === "connected") {
		setStatus("Live voice connected. Speak naturally.");
		el.liveConnectButton.textContent = "Disconnect live voice";
		el.interruptButton.disabled = false;
	    } else if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
		if (pc.connectionState !== "closed") {
		    setStatus(`Live connection ${pc.connectionState}.`);
		}
	    }
	};
	
	pc.ontrack = event => {
	    el.agentAudio.srcObject = event.streams[0];
	    // iOS may require this explicit call despite autoplay.
	    el.agentAudio.play().catch(() => {});
	};
	
	const dataChannel = pc.createDataChannel("oai-events");
	state.dataChannel = dataChannel;

	dataChannel.onmessage = event => {
	    if (epoch !== state.liveEpoch || state.dataChannel !== dataChannel) return;

	    try {
		handleRealtimeEvent(JSON.parse(event.data));
	    } catch (error) {
		console.warn("Could not parse Realtime event:", error, event.data);
	    }
	};
	
	dataChannel.onerror = error => console.error("Realtime data-channel error:", error);

	for (const track of state.localStream.getTracks()) {
	    pc.addTrack(track, state.localStream);
	}

	const offer = await pc.createOffer();
	await pc.setLocalDescription(offer);

	setStatus("Connecting to live voice…");

	const answerResponse = await fetch("https://api.openai.com/v1/realtime/calls", {
	    method: "POST",
	    headers: {
		"Authorization": `Bearer ${ephemeralToken}`,
		"Content-Type": "application/sdp"
	    },
	    body: offer.sdp
	});
	
	if (!answerResponse.ok) {
	    throw new Error(await answerResponse.text());
	}
	
	await pc.setRemoteDescription({
	    type: "answer",
	    sdp: await answerResponse.text()
	});
	
    } catch (error) {
	console.error(error);
	disconnectLive();
	setStatus(`Live connection error: ${error.message}`);
    } finally {
	if (epoch === state.liveEpoch) {
	    state.liveConnecting = false;
	}
    }
}

async function persistLiveMessage(role, content) {
  if (!content?.trim()) return;

  try {
    const response = await fetch(window.VOICE_ENDPOINTS.liveMessage, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
          log_filename: window.VOICE_CONFIG.log_filename,
	  profile_id: window.VOICE_CONFIG.profile_id,
        role,
        content
      })
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }
  } catch (error) {
    console.error("Could not persist Live message:", error);
  }
}


function responseMessageFor(event) {
  const responseId = event.response_id || event.response?.id || "unidentified-response";

  if (!state.liveAssistantMessages.has(responseId)) {
    state.liveAssistantMessages.set(
      responseId,
      addMessage("assistant", "", { partial: true })
    );
  }

  return state.liveAssistantMessages.get(responseId);
}

function handleRealtimeEvent(event) {
  /*
    Event naming has changed across Realtime API versions. These aliases make
    transcript rendering resilient while you inspect events in DevTools.
  */
  switch (event.type) {
  case "input_audio_buffer.speech_started":
      createPendingLiveUserMessage();
      break;

  case "conversation.item.input_audio_transcription.completed": {
      const itemId = event.item_id || crypto.randomUUID();

      if (!state.liveUserMessages.has(itemId)) {
	  const transcript = event.transcript || "";
	  const message = completePendingLiveUserMessage(transcript);
	  
	  state.liveUserMessages.set(itemId, message);
	  state.messages.push({ role: "user", content: transcript });
	  
	  if (transcript.trim() && !state.livePersistedUserItems.has(itemId)) {
	      state.livePersistedUserItems.add(itemId);
	      persistLiveMessage("user", transcript);
	  }
      }
      break;
  }

    case "response.created":
      responseMessageFor(event);
      break;

    case "response.output_audio_transcript.delta":
    case "response.audio_transcript.delta": {
      appendMessageText(responseMessageFor(event), event.delta || "");
      break;
    }

    case "response.output_audio_transcript.done":
    case "response.audio_transcript.done": {
	const message = responseMessageFor(event);
	
	if (!message.textContent && event.transcript) {
	    message.textContent = event.transcript;
	}
	
	finalizeMessage(message);
	break;
    }

    case "response.done": {
	const responseId =
	      event.response_id || event.response?.id || "unidentified-response";
	
	const message = responseMessageFor(event);
	finalizeMessage(message);
	
	const text = message.textContent.trim();

	if (text && !state.livePersistedAssistantResponses.has(responseId)) {
	    state.livePersistedAssistantResponses.add(responseId);
	    state.messages.push({ role: "assistant", content: text });
	    persistLiveMessage("assistant", text);
	}
	break;
    }
      
    case "error":
      console.error("OpenAI Realtime error:", event);
      setStatus(`Realtime error: ${event.error?.message || "unknown error"}`);
      break;
  }
}

async function sendEconomyText(inputText, {
  speakResponse = false,
  ...extraFields
} = {}) {
    const text = inputText.trim();
    if (!text) return;

    stopEconomyRequest();

    addMessage("user", text);
    state.messages.push({ role: "user", content: text });
    const assistantMessage = addMessage("assistant", "", { partial: true });

    const formData = new FormData();
    formData.set("input_text", text);
    formData.set("log_filename", window.VOICE_CONFIG.log_filename);
    formData.set("profile_id", window.VOICE_CONFIG.profile_id);
    formData.set("task", window.VOICE_TASK);
    
    if (selectedDocument()) {
	formData.set("document", selectedDocument());
    }
    
    for (const [key, value] of Object.entries(extraFields)) {
	formData.set(key, value);
    }

    const controller = new AbortController();
    state.economyAbortController = controller;
    el.interruptButton.disabled = false;

    try {
	setStatus("Thinking…");
	
	const response = await fetch(window.VOICE_ENDPOINTS.completion, {
	    method: "POST",
	    body: formData,
	    signal: controller.signal
	});

	if (!response.ok) {
	    throw new Error(await response.text() || `HTTP ${response.status}`);
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let result = "";

	while (true) {
	    const { done, value } = await reader.read();
	    if (done) break;
	    
	    const chunk = decoder.decode(value, { stream: true });
	    result += chunk;
	    appendMessageText(assistantMessage, chunk);
	}
	
	const finalChunk = decoder.decode();
	if (finalChunk) {
	    result += finalChunk;
	    appendMessageText(assistantMessage, finalChunk);
	}

	finalizeMessage(assistantMessage);
	state.messages.push({ role: "assistant", content: result });

	if (speakResponse) {
	    speakText(result);
	}


	setStatus("Ready.");

    } catch (error) {
	if (error.name === "AbortError") {
	    appendMessageText(assistantMessage, "\n\n[Stopped]");
	    finalizeMessage(assistantMessage);
	    setStatus("Stopped.");
	} else {
	    console.error(error);
	    assistantMessage.textContent = `Error: ${error.message}`;
	    finalizeMessage(assistantMessage);
	    setStatus("Request failed.");
	}
    } finally {
	if (state.economyAbortController === controller) {
	    state.economyAbortController = null;
	    el.interruptButton.disabled = !state.peerConnection;
	}
    }
}

async function streamReaderRequest(endpoint, formData, userLabel) {
  addMessage("user", userLabel);
  const assistantMessage = addMessage("assistant", "", { partial: true });

  const controller = new AbortController();
  state.economyAbortController = controller;
  el.interruptButton.disabled = false;

  try {
    setStatus("Reading…");

    const response = await fetch(endpoint, {
      method: "POST",
      body: formData,
      signal: controller.signal
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let result = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      result += chunk;
      appendMessageText(assistantMessage, chunk);
    }

    finalizeMessage(assistantMessage);
    state.messages.push({ role: "assistant", content: result });

    speakText(result);
    setStatus("Ready.");

  } catch (error) {
    assistantMessage.textContent =
      error.name === "AbortError" ? "[Stopped]" : `Error: ${error.message}`;
    finalizeMessage(assistantMessage);
    setStatus(error.name === "AbortError" ? "Stopped." : "Reader failed.");

  } finally {
    if (state.economyAbortController === controller) {
      state.economyAbortController = null;
      el.interruptButton.disabled = !state.peerConnection;
    }
  }
}


function emitReaderAction(action) {
  const document = selectedDocument();

  if (action === "document-status") {
    const params = new URLSearchParams({
      document,
      log_filename: window.VOICE_CONFIG.log_filename
    });

    fetch(`${window.VOICE_ENDPOINTS.readerStatus}?${params}`)
      .then(response => response.json())
      .then(status => {
        el.readerStatus.textContent =
          `Next page: ${status.nextpage} of ${status.total}.`;
      })
      .catch(() => {
        el.readerStatus.textContent = "Could not get document status.";
      });

    return;
  }

  const formData = new FormData();
  formData.set("document", document);
  formData.set("log_filename", window.VOICE_CONFIG.log_filename);

  if (action === "read-next") {
    streamReaderRequest(
      window.VOICE_ENDPOINTS.readerRead,
      formData,
      "[Reader: read next page]"
    );
  }

  if (action === "summarize") {
    streamReaderRequest(
      window.VOICE_ENDPOINTS.readerSummary,
      formData,
      "[Reader: summarize document]"
    );
  }
}

el.textForm.addEventListener("submit", event => {
  event.preventDefault();
  const text = el.textInput.value;
  el.textInput.value = "";
  el.textInput.style.height = "";

  // Typed requests use the cheaper text route even if Live is connected.
  sendEconomyText(text);
});

el.textInput.addEventListener("input", () => {
  el.textInput.style.height = "auto";
  el.textInput.style.height = `${Math.min(el.textInput.scrollHeight, 128)}px`;
});

el.modeButtons.forEach(button => {
  button.addEventListener("click", () => {
    setMode(button.dataset.mode);
  });
});

el.liveConnectButton.addEventListener("click", connectLive);
el.interruptButton.addEventListener("click", interruptEverything);

document.querySelectorAll("[data-reader-action]").forEach(button => {
  button.addEventListener("click", () => emitReaderAction(button.dataset.readerAction));
});

window.addEventListener("beforeunload", disconnectLive);

setMode("economy");

function populateSpeechVoices() {
  const voices = window.speechSynthesis?.getVoices() || [];
  const priorValue = el.speechVoice.value;

  el.speechVoice.replaceChildren();

  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = voice.voiceURI;
    option.textContent = `${voice.name} (${voice.lang})`;
    el.speechVoice.appendChild(option);
  }

  const preferred =
    voices.find(v => /Samantha|Karen|Ava|Zoe|Google US English/i.test(v.name)) ||
    voices.find(v => v.lang.startsWith("en")) ||
    voices[0];

  if (priorValue && voices.some(v => v.voiceURI === priorValue)) {
    el.speechVoice.value = priorValue;
  } else if (preferred) {
    el.speechVoice.value = preferred.voiceURI;
  }
}

function selectedSpeechVoice() {
  const uri = el.speechVoice.value;
  return (window.speechSynthesis?.getVoices() || [])
    .find(voice => voice.voiceURI === uri) || null;
}

function speakText(text) {
    if (!text?.trim() || !("speechSynthesis" in window)) return;

    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(speechSafeText(text));
  utterance.voice = selectedSpeechVoice();
  utterance.rate = Number(el.speechRate.value);
  utterance.pitch = Number(el.speechPitch.value);

  utterance.onstart = () => setStatus("Speaking. Hold mic button to interrupt.");
  utterance.onend = () => {
    if (!state.economyRecording) setStatus("Ready.");
  };
  utterance.onerror = () => {
    if (!state.economyRecording) setStatus("Ready.");
  };

  window.speechSynthesis.speak(utterance);
}

if ("speechSynthesis" in window) {
  speechSynthesis.addEventListener("voiceschanged", populateSpeechVoices);
  populateSpeechVoices();
}

el.speechRate.addEventListener("input", () => {
  el.speechRateValue.value = el.speechRate.value;
  el.speechRateValue.textContent = el.speechRate.value;
});

el.speechPitch.addEventListener("input", () => {
  el.speechPitchValue.value = el.speechPitch.value;
  el.speechPitchValue.textContent = el.speechPitch.value;
});

async function startEconomyRecording() {
  if (state.economyRecording) return;

  // Speaking must never feed back into the microphone interaction.
  window.speechSynthesis?.cancel();
  stopEconomyRequest();

  try {
    state.economyMicStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });

    const recorder = new MediaRecorder(state.economyMicStream, {
      mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : undefined
    });

    state.economyRecorder = recorder;
    state.economyAudioChunks = [];
    state.economyRecording = true;

    recorder.ondataavailable = event => {
      if (event.data.size > 0) state.economyAudioChunks.push(event.data);
    };

    recorder.onstop = transcribeEconomyRecording;

    recorder.start();
    el.economyMicButton.textContent = "Release to send";
    el.speechPreview.textContent = "Listening…";
    setStatus("Listening…");

  } catch (error) {
    console.error(error);
    setStatus(`Microphone error: ${error.message}`);
  }
}

function stopEconomyRecording() {
  if (!state.economyRecording || !state.economyRecorder) return;

  state.economyRecording = false;
  el.economyMicButton.textContent = "Hold to speak";
  state.economyRecorder.stop();
}

async function transcribeEconomyRecording() {
  const stream = state.economyMicStream;
  const chunks = state.economyAudioChunks;

  state.economyRecorder = null;
  state.economyMicStream = null;
  state.economyAudioChunks = [];

  for (const track of stream?.getTracks() || []) track.stop();

  if (!chunks.length) {
    el.speechPreview.textContent = "";
    setStatus("Ready.");
    return;
  }

  try {
    setStatus("Transcribing…");

    const blob = new Blob(chunks, { type: "audio/webm" });
    const form = new FormData();
    form.set("audio", blob, "speech.webm");

    const response = await fetch(window.VOICE_ENDPOINTS.economyTranscribe, {
      method: "POST",
      body: form
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Transcription failed.");
    }

      const text = data.text.trim();
      if (state.mailDraftThreadId) {
	  el.speechPreview.textContent = text;
	  await saveMailDraft(text);
	  return;
      }
    el.speechPreview.textContent = text;

    if (text) {
      await dispatchSpokenRequest(text);
    } else {
      setStatus("I did not catch that.");
    }

  } catch (error) {
    console.error(error);
    setStatus(`Transcription failed: ${error.message}`);
  }
}

el.economyMicButton.addEventListener("pointerdown", event => {
  event.preventDefault();
  el.economyMicButton.setPointerCapture?.(event.pointerId);
  startEconomyRecording();
});

for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) {
  el.economyMicButton.addEventListener(eventName, stopEconomyRecording);
}

async function dispatchSpokenRequest(text) {
    const normalized = text
	  .trim()
	  .toLowerCase()
	  .replace(/[^\w\s]/g, " ")  // commas, punctuation, etc.
	  .replace(/\s+/g, " ")
	  .trim();

    if (
	/^(?:next|read next|next page|read the next page)(?: please)?$/
	    .test(normalized)
    ) {
	emitReaderAction("read-next");
	return;
    }

    if (
	/^(?:summarize|summary|summarize document|summarize this document)(?: please)?$/
	    .test(normalized)
    ) {
	emitReaderAction("summarize");
	return;
    }
    
    if (
	/^(?:document status|status|where are we|what page are we on)(?: please)?$/
	    .test(normalized)
    ) {
	emitReaderAction("document-status");
	return;
    }

    const noteMatch = text.match(
	/^(?:note|make a note|reader note)\s*[:,]?\s+(.+)/i
    );

    if (noteMatch) {
	await saveReaderNote(noteMatch[1]);
	return;
    }

    // Ordinary spoken conversational question.
    sendEconomyText(text, { speakResponse: true });
}

async function saveReaderNote(note) {
  const form = new FormData();
  form.set("document", selectedDocument());
  form.set("log_filename", window.VOICE_CONFIG.log_filename);
  form.set("input_text", note);

  const response = await fetch(window.VOICE_ENDPOINTS.readerNote, {
    method: "POST",
    body: form
  });

  if (!response.ok) {
    throw new Error(await response.text() || "Could not save note.");
  }

  addMessage("user", `[Reader note] ${note}`);
  addMessage("assistant", "Noted.");
  speakText("Noted.");
  setStatus("Note saved.");
}

// Driving overlay

function closeDrivingOverlay() {
  el.drivingOverlay.hidden = true;
  el.drivingReopen.hidden = false;
}

function reopenDrivingOverlay() {
  el.drivingOverlay.hidden = false;
  el.drivingReopen.hidden = true;

  if (window.VOICE_TASK !== "mail") {
    updateDrivingOverlay();
  }
}

el.drivingClose?.addEventListener("click", closeDrivingOverlay);
el.drivingReopen?.addEventListener("click", reopenDrivingOverlay);

if (el.drivingOverlay && window.VOICE_TASK !== "mail") {
    
function updateDrivingOverlay() {
  const live = state.mode === "live";
  const reader = window.VOICE_TASK === "reader";

  el.drivingOverlay.classList.toggle("live", live);

  if (live) {
    el.drivingPrimary.querySelector(".driving-label").textContent =
      "Switch to Economy mode";
    el.drivingPrimary.querySelector(".driving-icon").textContent = "◁";
    el.drivingSecondary.hidden = true;
  } else {
    el.drivingPrimary.querySelector(".driving-label").textContent = "Push to talk";
    el.drivingPrimary.querySelector(".driving-icon").textContent = "◯";
    el.drivingSecondary.hidden = false;
    el.drivingSecondary.querySelector(".driving-label").textContent =
      reader ? "Next page" : "Switch to Live mode";
    el.drivingSecondary.querySelector(".driving-icon").textContent =
      reader ? "▷" : "◉";
  }
}

const originalSetMode = setMode;
setMode = function(mode) {
  originalSetMode(mode);
  updateDrivingOverlay();
};

el.drivingPrimary.addEventListener("pointerdown", event => {
  event.preventDefault();
  if (state.mode === "live") {
    setMode("economy");
  } else {
    startEconomyRecording();
  }
});

for (const eventName of ["pointerup", "pointercancel", "pointerleave"]) {
  el.drivingPrimary.addEventListener(eventName, () => {
    if (state.mode === "economy") stopEconomyRecording();
  });
}

el.drivingSecondary.addEventListener("click", async () => {
  if (window.VOICE_TASK === "reader") {
    emitReaderAction("read-next");
  } else {
    setMode("live");
  }
});

updateDrivingOverlay();

if ("mediaSession" in navigator) {
  navigator.mediaSession.setActionHandler("play", () => window.speechSynthesis.resume());
  navigator.mediaSession.setActionHandler("pause", () => window.speechSynthesis.pause());

  navigator.mediaSession.setActionHandler("nexttrack", () => {
    if (window.VOICE_TASK === "reader") emitReaderAction("read-next");
  });

  navigator.mediaSession.setActionHandler("previoustrack", () => {
    if (window.VOICE_TASK === "reader") emitReaderAction("read-previous");
  });
}

function syncReaderDocument(value) {
  if (el.readerDocument) el.readerDocument.value = value;
  if (el.drivingReaderDocument) el.drivingReaderDocument.value = value;
}

el.readerDocument?.addEventListener("change", event => {
  syncReaderDocument(event.target.value);
});

el.drivingReaderDocument?.addEventListener("change", event => {
  syncReaderDocument(event.target.value);
  el.readerStatus.textContent = "";
});

}

// Mail Behavior

function mailUrl(template, threadId) {
  return template.replace("THREAD_ID", encodeURIComponent(threadId));
}

function spokenHeader(value) {
  return (value || "")
    // “Jane Doe <jane@example.com>” -> “Jane Doe”
    .replace(/\s*<[^>\r\n]*>/g, "")
    // A bare email address, if no display name was supplied.
    .replace(/\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b/g, "email address omitted")
    .replace(/\s+/g, " ")
    .trim();
}

function speechSafeText(value) {
  return (value || "")
    // Never allow angle-bracket mail addresses / markup into platform TTS.
    .replace(/<[^>\r\n]*>/g, "")
    // URLs are unpleasant and may make voices stop or ramble.
    .replace(/\bhttps?:\/\/[^\s<>"']+/gi, "link omitted")
    .replace(/\bwww\.[^\s<>"']+/gi, "link omitted")
    // Bare addresses are usually not useful to hear.
    .replace(/\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b/g, "email address omitted")
    // A few characters can produce unusually bad TTS behavior.
    .replace(/[<>[\]{}|\\^_`~]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function loadMailQueue() {
  setStatus("Loading inbox…");

  const response = await fetch(window.VOICE_ENDPOINTS.mailConversations);
  const data = await response.json();

  if (!response.ok) throw new Error(data.error || "Could not load inbox.");

  state.mailQueue = data.conversations || [];
  state.mailCurrent = null;
}

async function playNextMail({ markCurrent = true } = {}) {
    stopMailPlayback();

    const controller = new AbortController();
    state.mailSpeechController = controller;
    const { signal } = controller;

    let assistantMessage = null;

    try {
        if (state.mailCurrent && markCurrent) {
            const readResponse = await fetch(
                mailUrl(
                    window.VOICE_ENDPOINTS.mailRead,
                    state.mailCurrent.thread_id
                ),
                { method: "POST", signal }
            );

            if (!readResponse.ok) {
                throw new Error("Could not mark the conversation as read.");
            }
        }

        if (signal.aborted) return;

        // Peek first: a failed fetch should not remove it from the queue.
        const summary = state.mailQueue[0];

        if (!summary) {
            state.mailCurrent = null;
            addMessage("assistant", "Your inbox queue is complete.");
            speakText("Your inbox queue is complete.");
            setStatus("Inbox complete.");
            return;
        }

        setStatus("Loading conversation…");

        const response = await fetch(
            mailUrl(
                window.VOICE_ENDPOINTS.mailConversation,
                summary.thread_id
            ),
            { signal }
        );
        const conversation = await response.json();

        if (!response.ok) {
            throw new Error(
                conversation.error || "Could not load conversation."
            );
        }

        if (signal.aborted) return;

        state.mailCurrent = {
            ...conversation,
            unread: summary.unread
        };

        setStatus("Preparing spoken email…");

        const speechResponse = await fetch(
            mailUrl(
                window.VOICE_ENDPOINTS.mailSpeech,
                summary.thread_id
            ),
            { signal }
        );

	console.log("AA");

	if (!speechResponse.ok || !speechResponse.body) {
            const error = await speechResponse.text();
            throw new Error(error || "Could not prepare email speech.");
        }

        // Remove only after both conversation and speech stream are available.
        state.mailQueue.shift();

	console.log("BB");

        const latest = state.mailCurrent.latest;
        const header = [
            state.mailCurrent.unread
                ? "Unread conversation."
                : "Read conversation.",
            `${state.mailCurrent.message_count} message${
                state.mailCurrent.message_count === 1 ? "" : "s"
            }.`,
            `From ${spokenHeader(latest.from) || "an unknown sender"}.`,
            `Subject: ${speechSafeText(latest.subject) || "no subject"}.`,
        ].join(" ");

        assistantMessage = addMessage("assistant", `${header} `, {
            partial: true
        });

	console.log("CC");

        const speaker = createMailSpeaker(signal);
        speaker.write(header);

        const reader = speechResponse.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });

            if (chunk) {
                appendMessageText(assistantMessage, chunk);
                speaker.write(chunk);
            }
        }

	console.log("DD");

        const finalChunk = decoder.decode();
        if (finalChunk) {
            appendMessageText(assistantMessage, finalChunk);
            speaker.write(finalChunk);
        }

        finalizeMessage(assistantMessage);
        speaker.finish();

    } catch (error) {
        if (error.name === "AbortError") {
            if (assistantMessage) {
                appendMessageText(assistantMessage, "\n\n[Stopped]");
                finalizeMessage(assistantMessage);
            }
            setStatus("Stopped.");
            return;
        }

        console.error(error);
        setStatus(`Mail error: ${error.message}`);
    } finally {
        if (state.mailSpeechController === controller) {
            state.mailSpeechController = null;
        }
    }
}

async function archiveCurrentMail() {
    stopMailPlayback();
    
  if (!state.mailCurrent) {
    await playNextMail({ markCurrent: false });
    return;
  }

  const threadId = state.mailCurrent.thread_id;

  const response = await fetch(
    mailUrl(window.VOICE_ENDPOINTS.mailArchive, threadId),
    { method: "POST" }
  );

  if (!response.ok) {
    throw new Error(await response.text());
  }

  speakText("Archived.");
  await playNextMail({ markCurrent: false });
}

async function saveMailDraft(text) {
    stopMailPlayback();

  const threadId = state.mailDraftThreadId;
  state.mailDraftThreadId = null;

  if (!threadId || !text?.trim()) {
    setStatus("No draft text received.");
    return;
  }

  const response = await fetch(
    mailUrl(window.VOICE_ENDPOINTS.mailDraft, threadId),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    }
  );

  if (!response.ok) throw new Error(await response.text());

  addMessage("assistant", "Draft saved. It has not been sent.");
  speakText("Draft saved. It has not been sent.");
  setStatus("Draft saved.");
}

if (window.VOICE_TASK === "mail") {
    function primeSpeech() {
	const synth = window.speechSynthesis;
	if (!synth) return;
	synth.resume();
    }

    el.mailNext?.addEventListener("click", () => {
	primeSpeech();
	playNextMail().catch(error => setStatus(`Mail error: ${error.message}`));
    });

    el.mailArchive?.addEventListener("click", () => {
	primeSpeech();
	archiveCurrentMail().catch(error => setStatus(`Mail error: ${error.message}`));
    });

  el.mailDraft?.addEventListener("click", () => {
    if (!state.mailCurrent) {
      speakText("There is no current conversation to reply to.");
      return;
    }

    state.mailDraftThreadId = state.mailCurrent.thread_id;
    el.speechPreview.textContent = "Dictate your draft reply, then release.";
    startEconomyRecording();
  });

    loadMailQueue()
	.then(() => {
	    setStatus("Inbox loaded. Press Play next to begin.");
	    addMessage("assistant", "Inbox loaded. Press Play next to begin.");
	})
	.catch(error => setStatus(`Mail error: ${error.message}`));
}

function stopMailPlayback() {
  state.mailSpeechController?.abort();
  state.mailSpeechController = null;
  state.mailSpeechUtterance = null;

  const synth = window.speechSynthesis;
  if (synth) {
    synth.cancel();

    // Particularly useful for Safari after interruption/backgrounding.
    setTimeout(() => synth.resume(), 0);
  }
}

function createMailSpeaker(signal) {
    const synth = window.speechSynthesis;
    const queue = [];
    let buffer = "";
    let speaking = false;
    let finished = false;

    function pump() {
        if (signal.aborted || speaking) return;

        if (!queue.length) {
            if (finished) setStatus("Ready.");
            return;
        }

        // Text still appears in the transcript on browsers without TTS.
        if (!synth) {
            queue.length = 0;
            if (finished) setStatus("Ready.");
            return;
        }

        const utterance = new SpeechSynthesisUtterance(queue.shift());
        utterance.voice = selectedSpeechVoice();
        utterance.rate = Number(el.speechRate.value);
        utterance.pitch = Number(el.speechPitch.value);

        speaking = true;

        // Retain a reference throughout playback.
        state.mailSpeechUtterance = utterance;

        const advance = () => {
            if (signal.aborted) return;

            speaking = false;
            if (state.mailSpeechUtterance === utterance) {
                state.mailSpeechUtterance = null;
            }
            pump();
        };

        utterance.onend = advance;
        utterance.onerror = advance;
        utterance.onstart = () => {
            if (!signal.aborted) setStatus("Reading mail.");
        };

	console.debug("Mail TTS speak", {
	    text: utterance.text,
	    speaking: synth.speaking,
	    pending: synth.pending,
	    paused: synth.paused,
	    aborted: signal.aborted
	});

	utterance.onerror = event => {
	    console.warn("Mail TTS error:", event.error, event);
	    advance();
	};

	setTimeout(() => {
	    if (signal.aborted) return;
	    
	    synth.resume();

	    try {
		synth.speak(utterance);
	    } catch (error) {
		console.error("Mail TTS speak() failed:", error);
		speaking = false;
		advance();
	    }
	}, 50);
    }

    function emit(text) {
        const cleaned = speechSafeText(text);
        if (cleaned) queue.push(cleaned);
    }

    function drain(flush = false) {
        while (buffer.length) {
            // Prefer a sentence boundary within a short utterance.
            const sentence = buffer.slice(0, 260)
                .match(/[.!?](?:\s+|$)/);

            let cut;

            if (sentence) {
                cut = sentence.index + sentence[0].length;
            } else if (buffer.length >= 260) {
                const space = buffer.lastIndexOf(" ", 260);
                cut = space >= 100 ? space : 260;
            } else if (flush) {
                cut = buffer.length;
            } else {
                break;
            }

            emit(buffer.slice(0, cut));
            buffer = buffer.slice(cut);
        }

        pump();
    }

    return {
        write(text) {
            if (signal.aborted) return;
            buffer += text;
            drain();
        },

        finish() {
            if (signal.aborted) return;
            finished = true;
            drain(true);
        }
    };
}
