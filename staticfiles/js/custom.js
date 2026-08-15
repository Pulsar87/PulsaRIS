const searchInput = document.getElementById("searchInput");
const dateFrom = document.getElementById("dateFrom");
const dateTo = document.getElementById("dateTo");
const checkboxes = document.querySelectorAll(".filter-checkbox");
const rows = document.querySelectorAll(".worklist-row");

function applyFilters() {
  const searchTerm = searchInput.value.toLowerCase();
  const fromVal = dateFrom.value; // YYYY-MM-DD
  const toVal = dateTo.value; // YYYY-MM-DD

  const selectedMods = Array.from(
    document.querySelectorAll('input[data-filter="modality"]:checked'),
  ).map((cb) => cb.value);
  const selectedStats = Array.from(
    document.querySelectorAll('input[data-filter="status"]:checked'),
  ).map((cb) => cb.value);

  let visibleCount = 0;

  rows.forEach((row) => {
    const text = row.innerText.toLowerCase();
    const mod = row.getAttribute("data-modality");
    const stat = row.getAttribute("data-status");
    const rowDate = row.getAttribute("data-date"); // YYYY-MM-DD from our data-attribute

    const matchesSearch = text.includes(searchTerm);
    const matchesMod = selectedMods.length === 0 || selectedMods.includes(mod);
    const matchesStat =
      selectedStats.length === 0 || selectedStats.includes(stat);

    // Date Range Logic
    let matchesDate = true;
    if (fromVal && rowDate < fromVal) matchesDate = false;
    if (toVal && rowDate > toVal) matchesDate = false;

    if (matchesSearch && matchesMod && matchesStat && matchesDate) {
      row.style.display = "";
      visibleCount++;
    } else {
      row.style.display = "none";
    }
  });

  document.getElementById("recordCount").innerText = visibleCount;
}

// Quick Range Helper
function setQuickRange(range) {
  const today = new Date().toISOString().split("T")[0];

  if (range === "all") {
    dateFrom.value = "";
    dateTo.value = "";
  } else if (range === "today") {
    dateFrom.value = today;
    dateTo.value = today;
  } else if (range === "yesterday") {
    const yestDate = new Date();
    yestDate.setDate(yestDate.getDate() - 1);
    const yesterday = yestDate.toISOString().split("T")[0];
    dateFrom.value = yesterday;
    dateTo.value = yesterday;
  }

  applyFilters();
}

// Listeners
searchInput.addEventListener("keyup", applyFilters);
dateFrom.addEventListener("change", applyFilters);
dateTo.addEventListener("change", applyFilters);
checkboxes.forEach((cb) => cb.addEventListener("change", applyFilters));

document.addEventListener("DOMContentLoaded", function () {
  const toasts = document.querySelectorAll(".toast");
  toasts.forEach((toast) => {
    setTimeout(() => {
      const bsToast =
        bootstrap.Toast.getInstance(toast) || new bootstrap.Toast(toast);
      bsToast.hide();
      toast.addEventListener("hidden.bs.toast", () => toast.remove());
    }, 5000);
  });
});

// Theme Switcher Logic
const getStoredTheme = () => localStorage.getItem("theme");
const setStoredTheme = (theme) => localStorage.setItem("theme", theme);

const getPreferredTheme = () => {
  const storedTheme = getStoredTheme();
  if (storedTheme) return storedTheme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
};

const setTheme = (theme) => {
  document.documentElement.setAttribute("data-bs-theme", theme);
};

function updateThemeIcon(theme) {
  const themeToggle = document.getElementById("theme-toggle");
  if (!themeToggle) return;
  // If dark mode is active, show sun icon (to indicate switching to light)
  // If light mode is active, show moon icon (to indicate switching to dark)
  if (theme === "dark") {
    themeToggle.innerHTML = '<i class="bi bi-sun-fill"></i>';
  } else {
    themeToggle.innerHTML = '<i class="bi bi-moon-stars-fill"></i>';
  }
}

// Apply theme on page load
const initialTheme = getPreferredTheme();
setTheme(initialTheme);
updateThemeIcon(initialTheme);

// Setup theme toggle button
function initThemeToggle() {
  const themeToggle = document.getElementById("theme-toggle");
  if (!themeToggle) return;

  themeToggle.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-bs-theme");
    const newTheme = currentTheme === "dark" ? "light" : "dark";
    setTheme(newTheme);
    setStoredTheme(newTheme);
    updateThemeIcon(newTheme);
  });
}

// Initialize when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initThemeToggle);
} else {
  initThemeToggle();
}

async function saveAllSettings() {
  const form = document.getElementById("settingsForm");
  const formData = new FormData(form);
  const settings = {};

  // 1. Convert FormData to a clean JSON object
  formData.forEach((value, key) => {
    // Handle checkboxes/multi-selects as arrays
    if (settings[key]) {
      if (!Array.isArray(settings[key])) {
        settings[key] = [settings[key]];
      }
      settings[key].push(value);
    } else {
      settings[key] = value;
    }
  });

  // 2. Send to the API
  try {
    const response = await fetch("/api/settings/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });

    const result = await response.json();

    if (result.status === "success") {
      showToast(
        "Settings Saved!",
        "Your changes are now live across the system.",
        "success",
      );
      // Reload after a short delay to let the CSS variables refresh
      setTimeout(() => window.location.reload(), 1500);
    }
  } catch (err) {
    showToast("Error", "Could not save settings.", "danger");
  }
}

function submitPayment(orderId) {
    const method = document.querySelector('input[name="method"]:checked').value;
    const formData = new FormData();
    formData.append('payment_method', method);

    fetch(`/api/collect_payment/${orderId}`, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            // Close modal and refresh to see status change
            location.reload();
        } else {
            alert("Payment failed: " + data.message);
        }
    });
}
