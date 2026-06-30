/* global $, showSpinner, hideSpinner */

function refreshValidationCallout () {
  if (window.QSValidationCallouts && typeof window.QSValidationCallouts.refresh === 'function') {
    window.QSValidationCallouts.refresh('tvdb_validated')
  }
}

function setToggleButtonIcon (button, showPlainText) {
  if (!button) return
  const icon = document.createElement('i')
  icon.className = showPlainText ? 'fas fa-eye-slash' : 'fas fa-eye'
  button.replaceChildren(icon)
}

function bindSecretToggle (buttonId, inputId) {
  const button = document.getElementById(buttonId)
  const input = document.getElementById(inputId)
  if (!button || !input) return

  if (input.value.trim() === '') {
    input.setAttribute('type', 'text')
    setToggleButtonIcon(button, true)
  } else {
    input.setAttribute('type', 'password')
    setToggleButtonIcon(button, false)
  }

  button.addEventListener('click', function () {
    const currentType = input.getAttribute('type')
    input.setAttribute('type', currentType === 'password' ? 'text' : 'password')
    setToggleButtonIcon(button, currentType === 'password')
  })
}

const validatedAtInput = document.getElementById('tvdb_validated_at')

$(document).ready(function () {
  const apiKeyInput = document.getElementById('tvdb_apikey')
  const pinInput = document.getElementById('tvdb_pin')
  const validateButton = document.getElementById('validateButton')
  const isValidated = document.getElementById('tvdb_validated').value.toLowerCase()

  bindSecretToggle('toggleApikeyVisibility', 'tvdb_apikey')
  bindSecretToggle('togglePinVisibility', 'tvdb_pin')

  validateButton.disabled = isValidated === 'true'

  function resetValidation () {
    document.getElementById('tvdb_validated').value = 'false'
    if (validatedAtInput) validatedAtInput.value = ''
    validateButton.disabled = false
    refreshValidationCallout()
  }

  apiKeyInput.addEventListener('input', resetValidation)
  pinInput.addEventListener('input', resetValidation)
})

document.getElementById('validateButton').addEventListener('click', function () {
  const apiKey = document.getElementById('tvdb_apikey').value
  const pin = document.getElementById('tvdb_pin').value
  const statusMessage = document.getElementById('statusMessage')

  if (!apiKey) {
    statusMessage.textContent = 'Please enter a TVDb API key.'
    statusMessage.style.color = '#ea868f'
    statusMessage.style.display = 'block'
    return
  }

  showSpinner('validate')

  fetch('/validate_tvdb', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ tvdb_apikey: apiKey, tvdb_pin: pin })
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.valid) {
        document.getElementById('tvdb_validated').value = 'true'
        if (validatedAtInput) validatedAtInput.value = new Date().toISOString()
        refreshValidationCallout()
        statusMessage.textContent = 'TVDb API key is valid.'
        statusMessage.style.color = '#75b798'
        document.getElementById('validateButton').disabled = true
      } else {
        document.getElementById('tvdb_validated').value = 'false'
        if (validatedAtInput) validatedAtInput.value = ''
        statusMessage.textContent = data.message || 'TVDb API key is invalid.'
        statusMessage.style.color = '#ea868f'
        refreshValidationCallout()
      }
      statusMessage.style.display = 'block'
    })
    .catch(error => {
      console.error('Error validating TVDb server:', error)
      statusMessage.textContent = 'Error validating TVDb API key.'
      statusMessage.style.color = '#ea868f'
      statusMessage.style.display = 'block'
      document.getElementById('tvdb_validated').value = 'false'
      if (validatedAtInput) validatedAtInput.value = ''
      refreshValidationCallout()
    })
    .finally(() => {
      hideSpinner('validate')
    })
})

document.getElementById('configForm').addEventListener('submit', function () {
  const apiKeyInput = document.getElementById('tvdb_apikey')
  const pinInput = document.getElementById('tvdb_pin')
  if (!apiKeyInput.value) apiKeyInput.value = ''
  if (!pinInput.value) pinInput.value = ''
})
