document.addEventListener("DOMContentLoaded", () => {
  const dateInput = document.querySelector("[data-date-picker]");
  const datePickerButton = document.querySelector("[data-open-date-picker]");
  const dateForm = document.querySelector(".appointment-date-form");

  datePickerButton?.addEventListener("click", () => {
    if (typeof dateInput.showPicker === "function") {
      dateInput.showPicker();
    } else {
      dateInput.focus();
      dateInput.click();
    }
  });
  dateInput?.addEventListener("change", () => dateForm.requestSubmit());

  const form = document.querySelector("[data-appointment-form]");
  if (!form) return;

  const timeSelect = form.querySelector("[data-appointment-time]");
  const durationFieldset = form.querySelector("[data-duration-options]");
  const durationInputs = Array.from(
    form.querySelectorAll('input[name="duration_minutes"]'),
  );
  const submitButton = form.querySelector(".appointment-submit");
  const summary = form.querySelector("[data-selection-summary]");

  const updateState = () => {
    const selectedTime = timeSelect.selectedOptions[0];
    const availability = new Map();
    if (selectedTime?.dataset.availability) {
      selectedTime.dataset.availability.split(",").forEach((entry) => {
        const [minutes, units] = entry.split(":").map(Number);
        availability.set(minutes, units);
      });
    }

    durationFieldset.disabled = availability.size === 0;
    durationInputs.forEach((input) => {
      const availableUnits = availability.get(Number(input.value));
      input.disabled = availableUnits === undefined;
      input.closest(".duration-choice").classList.toggle(
        "duration-choice-unavailable",
        availableUnits === undefined,
      );
      input.closest(".duration-choice").querySelector("small").textContent =
        availableUnits === undefined
          ? "Unavailable"
          : `${availableUnits} ${availableUnits === 1 ? "unit" : "units"} free`;
    });

    const selectedDuration = durationInputs.find((input) => input.checked);
    const durationAvailable =
      selectedDuration && availability.has(Number(selectedDuration.value));
    if (submitButton instanceof HTMLButtonElement) {
      submitButton.disabled = !selectedTime?.value || !durationAvailable;
    } else if (submitButton instanceof HTMLAnchorElement) {
      submitButton.setAttribute(
        "aria-disabled",
        String(!selectedTime?.value || !durationAvailable),
      );
    }

    if (!selectedTime?.value) {
      summary.textContent = "Choose a time and duration to continue.";
    } else if (!durationAvailable) {
      summary.textContent = `${selectedTime.textContent} · Choose a duration.`;
    } else {
      const durationLabel = {
        60: "1 hour",
        90: "1.5 hours",
        120: "2 hours",
      }[selectedDuration.value];
      summary.textContent = `${selectedTime.textContent} · ${durationLabel}`;
    }
  };

  timeSelect.addEventListener("change", () => {
    durationInputs.forEach((input) => {
      input.checked = false;
    });
    updateState();
  });
  durationInputs.forEach((input) => {
    input.addEventListener("change", updateState);
  });
  if (submitButton instanceof HTMLAnchorElement) {
    submitButton.addEventListener("click", (event) => {
      if (submitButton.getAttribute("aria-disabled") === "true") {
        event.preventDefault();
      }
    });
  }
  updateState();
});
