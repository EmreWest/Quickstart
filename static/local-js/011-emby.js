function refreshEmbyValidationCallout () {
  if (window.QSValidationCallouts && typeof window.QSValidationCallouts.refresh === 'function') {
    window.QSValidationCallouts.refresh('emby_validated')
  }
}

function setEmbyValidated (isValid) {
  const input = document.getElementById('emby_validated')
  const validatedAtInput = document.getElementById('emby_validated_at')
  if (input) input.value = isValid ? 'true' : 'false'
  if (validatedAtInput) validatedAtInput.value = isValid ? new Date().toISOString() : ''
  refreshEmbyValidationCallout()
}

document.addEventListener('DOMContentLoaded', function () {
  const validateButton = document.getElementById('validateEmbyButton')
  const toggleButton = document.getElementById('toggleEmbyApiKeyVisibility')
  const apiKeyInput = document.getElementById('emby_api_key')
  const statusMessage = document.getElementById('embyStatusMessage')
  const inputs = ['emby_url', 'emby_api_key', 'emby_user_id'].map(id => document.getElementById(id)).filter(Boolean)

  if (validateButton) {
    validateButton.disabled = String(document.getElementById('emby_validated').value || '').toLowerCase() === 'true'
  }

  if (toggleButton && apiKeyInput) {
    toggleButton.addEventListener('click', function () {
      const currentType = apiKeyInput.getAttribute('type')
      apiKeyInput.setAttribute('type', currentType === 'password' ? 'text' : 'password')
      const icon = document.createElement('i')
      icon.className = currentType === 'password' ? 'fas fa-eye-slash' : 'fas fa-eye'
      toggleButton.replaceChildren(icon)
    })
  }

  inputs.forEach(input => {
    input.addEventListener('input', function () {
      if (validateButton) validateButton.disabled = false
      setEmbyValidated(false)
    })
  })

  if (!validateButton) return
  validateButton.addEventListener('click', function () {
    const embyUrl = document.getElementById('emby_url').value
    const embyApiKey = document.getElementById('emby_api_key').value
    const embyUserId = document.getElementById('emby_user_id').value

    if (!embyUrl || !embyApiKey || !embyUserId) {
      statusMessage.textContent = 'Please enter Emby URL, API Key, and User ID.'
      statusMessage.style.color = '#ea868f'
      statusMessage.style.display = 'block'
      return
    }

    validateButton.disabled = true
    fetch('/validate_emby', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ emby_url: embyUrl, emby_api_key: embyApiKey, emby_user_id: embyUserId })
    })
      .then(response => response.json().then(data => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        if (ok && data.validated) {
          setEmbyValidated(true)
          statusMessage.textContent = 'Emby settings validated successfully.'
          statusMessage.style.color = '#75b798'
        } else {
          setEmbyValidated(false)
          validateButton.disabled = false
          statusMessage.textContent = data.error || 'Failed to validate Emby settings.'
          statusMessage.style.color = '#ea868f'
        }
        statusMessage.style.display = 'block'
      })
      .catch(() => {
        setEmbyValidated(false)
        validateButton.disabled = false
        statusMessage.textContent = 'Error occurred during validation.'
        statusMessage.style.color = '#ea868f'
        statusMessage.style.display = 'block'
      })
  })
})
