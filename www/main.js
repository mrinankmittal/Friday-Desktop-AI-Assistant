document.addEventListener("DOMContentLoaded", function () {

    const siriMessage = document.getElementById("siri-message");
    let currentMessageIndex = 0;
    let fadeTimeout;
    let nextMessageTimeout;

    function showSiriMessages(messages) {
        if (!siriMessage) {
            console.error("Siri message element was not found.");
            return;
        }

        const messageList = (Array.isArray(messages) ? messages : [messages])
            .filter(function (message) {
                return message !== null && message !== undefined;
            })
            .map(function (message) {
                return String(message);
            });

        if (messageList.length === 0) {
            return;
        }

        clearTimeout(fadeTimeout);
        clearTimeout(nextMessageTimeout);
        currentMessageIndex = 0;

        function animateSiriMessage() {
            siriMessage.classList.remove("siri-fade-in", "siri-fade-out");
            siriMessage.textContent = messageList[currentMessageIndex];

            // Force the browser to restart the CSS animation.
            void siriMessage.offsetWidth;
            siriMessage.classList.add("siri-fade-in");

            // A single message remains visible after fading in.
            if (messageList.length === 1) {
                return;
            }

            fadeTimeout = setTimeout(function () {
                siriMessage.classList.remove("siri-fade-in");
                siriMessage.classList.add("siri-fade-out");
            }, 2000);

            nextMessageTimeout = setTimeout(function () {
                currentMessageIndex =
                    (currentMessageIndex + 1) % messageList.length;
                animateSiriMessage();
            }, 3000);
        }

        animateSiriMessage();
    }

    // Make the function available to other scripts and Eel callbacks.
    window.showSiriMessages = showSiriMessages;

    const orb = window.FridayOrb;

    function setOrbState(state, status) {
        if (orb) {
            orb.setState(state, status ? { status: status } : undefined);
        }
    }

    eel.playAssistantSound()

    // One line, not a cycle: the caption now lives under the orb permanently,
    // and a rotating list leaves it blank between fades.
    showSiriMessages(["Hi, I am F.R.I.D.A.Y"]);

    const micButton = document.getElementById("MicBtn");

    /* Every activation path lands here: the hotword, the microphone button and
     * Alt+J. The orb stays on screen and changes state instead of swapping the
     * view out, so Friday is never replaced by a waveform. */
    function startVoiceSession(leftover) {
        const command = String(leftover ?? "").trim();

        setOrbState("listening");
        showSiriMessages(command ? [command] : ["Listening..."]);

        try {
            if (command) {
                eel.allCommands(command, true);
            } else {
                eel.allCommands();
            }
        } catch (error) {
            console.error("Unable to take voice command:", error);
            setOrbState("idle");
            showSiriMessages(["Sorry, I could not hear your command."]);
        }
    }

    if (micButton) {
        micButton.addEventListener("click", function (event) {
            event.preventDefault();
            startVoiceSession("");
        });
    }

    const stopListenBtn = document.getElementById("StopListenBtn");
    if (stopListenBtn) {
        stopListenBtn.addEventListener("click", async function (event) {
            event.preventDefault();
            setOrbState("idle");
            try {
                await eel.stopVoiceControl()();
            } catch (error) {
                console.error("Unable to stop listening:", error);
            }
        });
    }

    function TriggerVoiceControl(command) {
        startVoiceSession(command);
        return null;
    }

    // Let the Python UI process activate listening without simulated keys.
    eel.expose(TriggerVoiceControl);

    // Python drives the orb through the voice loop: listening, thinking,
    // speaking, then back to idle.
    function SetOrbState(state, status) {
        setOrbState(state, status ? String(status) : "");
        return null;
    }

    eel.expose(SetOrbState);

    // Ctrl+J is reserved by Edge for Downloads, so use Alt+J instead.
    function handleVoiceShortcut(event) {
        const isAltJ = event.altKey && event.code === "KeyJ";

        if (!isAltJ || event.repeat) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        eel.playAssistantSound();

        // Reuse the microphone handler so both activation methods behave alike.
        if (micButton) {
            micButton.click();
        }
    }

    document.addEventListener("keydown", handleVoiceShortcut, true);

    function PlayAssistant(message) {
        const command = String(message ?? "").trim();

        if (!command) {
            return;
        }

        const chatbox = document.getElementById("chatbox");
        const sendButton = document.getElementById("SendBtn");

        setOrbState("thinking");
        showSiriMessages([command]);

        if (chatbox) {
            chatbox.value = "";
        }

        if (micButton) {
            micButton.hidden = false;
        }

        if (sendButton) {
            sendButton.hidden = true;
        }

        eel.allCommands(command);
    }

    function ShowHideButton(message) {
        const hasMessage = String(message ?? "").trim().length > 0;
        const sendButton = document.getElementById("SendBtn");

        if (micButton) {
            micButton.hidden = hasMessage;
        }

        if (sendButton) {
            sendButton.hidden = !hasMessage;
        }
    }

    const chatbox = document.getElementById("chatbox");
    const sendButton = document.getElementById("SendBtn");

    if (chatbox) {
        chatbox.addEventListener("input", function () {
            ShowHideButton(chatbox.value);
        });

        chatbox.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
                PlayAssistant(chatbox.value);
            }
        });

        ShowHideButton(chatbox.value);
    }

    if (sendButton) {
        sendButton.addEventListener("click", function (event) {
            event.preventDefault();
            PlayAssistant(chatbox ? chatbox.value : "");
        });
    }

    
});
