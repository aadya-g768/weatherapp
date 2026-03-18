const assistantForm = document.querySelector("#assistant-form");
const assistantInput = document.querySelector("#assistant-input");
const assistantMessages = document.querySelector("#assistant-messages");
const assistantSubmit = document.querySelector("#assistant-submit");

const renderAssistantMessage = (role, message) => {
  if (!assistantMessages) {
    return;
  }

  const bubble = document.createElement("div");
  bubble.className = `assistant-message ${role === "user" ? "assistant-message--user" : "assistant-message--ai"}`;
  bubble.textContent = message;
  assistantMessages.appendChild(bubble);
  assistantMessages.scrollTop = assistantMessages.scrollHeight;
};

if (assistantForm && assistantInput && assistantSubmit) {
  assistantForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const message = assistantInput.value.trim();
    if (!message) {
      return;
    }

    renderAssistantMessage("user", message);
    assistantInput.value = "";
    assistantSubmit.disabled = true;
    assistantSubmit.textContent = "Thinking...";

    try {
      const response = await fetch("/api/assistant", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message }),
      });

      const data = await response.json();
      if (!response.ok || !data.ok) {
        renderAssistantMessage("ai", data.message || "I could not answer that right now.");
        return;
      }

      renderAssistantMessage("ai", data.reply || "I could not generate a response.");
    } catch (error) {
      renderAssistantMessage("ai", "Network error. Please try again.");
    } finally {
      assistantSubmit.disabled = false;
      assistantSubmit.textContent = "Ask AI";
      assistantInput.focus();
    }
  });
}
