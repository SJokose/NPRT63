// ===== Form Validation =====
document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.classList.add('fade');
            setTimeout(() => alert.remove(), 300);
        }, 5000);
    });
});

// ===== SA ID Validation =====
function validateSAID(saId) {
    // Remove any non-digit characters
    saId = saId.replace(/\D/g, '');
    
    if (saId.length !== 13) {
        return { valid: false, message: 'SA ID must be exactly 13 digits' };
    }
    
    // Luhn algorithm validation
    let total = 0;
    for (let i = 0; i < 12; i++) {
        let digit = parseInt(saId[11 - i]);
        if (i % 2 === 0) {
            digit *= 2;
            if (digit > 9) {
                digit -= 9;
            }
        }
        total += digit;
    }
    
    const checkDigit = (10 - (total % 10)) % 10;
    const isValid = checkDigit === parseInt(saId[12]);
    
    return {
        valid: isValid,
        message: isValid ? 'Valid SA ID' : 'Invalid SA ID'
    };
}

// ===== Phone Number Formatting =====
function formatPhoneNumber(input) {
    let value = input.value.replace(/\D/g, '');
    if (value.length > 0) {
        if (value.startsWith('0')) {
            value = '27' + value.substring(1);
        }
        if (value.length === 11 && !value.startsWith('27')) {
            value = '27' + value;
        }
    }
    input.value = value;
}

// ===== Date Validation =====
function validateDateOfBirth(dateInput) {
    const date = new Date(dateInput.value);
    const today = new Date();
    const minDate = new Date();
    minDate.setFullYear(today.getFullYear() - 120);
    
    if (date > today) {
        return { valid: false, message: 'Date of birth cannot be in the future' };
    }
    if (date < minDate) {
        return { valid: false, message: 'Please enter a valid date of birth' };
    }
    return { valid: true, message: 'Valid date of birth' };
}

// ===== Password Strength Checker =====
function checkPasswordStrength(password) {
    let strength = 0;
    const feedback = [];
    
    if (password.length >= 8) strength++;
    else feedback.push('At least 8 characters');
    
    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) strength++;
    else feedback.push('Include uppercase and lowercase letters');
    
    if (/\d/.test(password)) strength++;
    else feedback.push('Include at least one number');
    
    if (/[^a-zA-Z0-9]/.test(password)) strength++;
    else feedback.push('Include at least one special character');
    
    let level = '';
    let color = '';
    if (strength === 0 || strength === 1) {
        level = 'Weak';
        color = 'danger';
    } else if (strength === 2) {
        level = 'Medium';
        color = 'warning';
    } else if (strength === 3) {
        level = 'Strong';
        color = 'info';
    } else {
        level = 'Very Strong';
        color = 'success';
    }
    
    return {
        level: level,
        color: color,
        feedback: feedback
    };
}

// ===== Password Match Check =====
function checkPasswordMatch(password1, password2) {
    return password1 === password2;
}

// ===== Auto-save Form Data =====
class AutoSave {
    constructor(formId, storageKey) {
        this.form = document.getElementById(formId);
        this.storageKey = storageKey;
        this.timer = null;
        this.init();
    }
    
    init() {
        if (!this.form) return;
        
        // Load saved data
        this.loadData();
        
        // Save on input change
        this.form.querySelectorAll('input, textarea, select').forEach(field => {
            field.addEventListener('input', () => {
                this.saveData();
            });
            field.addEventListener('change', () => {
                this.saveData();
            });
        });
        
        // Clear data on submit
        this.form.addEventListener('submit', () => {
            localStorage.removeItem(this.storageKey);
        });
    }
    
    saveData() {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => {
            const data = {};
            this.form.querySelectorAll('input, textarea, select').forEach(field => {
                if (field.name && field.name !== 'csrfmiddlewaretoken') {
                    data[field.name] = field.value;
                }
            });
            localStorage.setItem(this.storageKey, JSON.stringify(data));
        }, 500);
    }
    
    loadData() {
        const saved = localStorage.getItem(this.storageKey);
        if (saved) {
            try {
                const data = JSON.parse(saved);
                this.form.querySelectorAll('input, textarea, select').forEach(field => {
                    if (field.name && data[field.name] !== undefined) {
                        field.value = data[field.name];
                    }
                });
            } catch (e) {
                console.error('Error loading saved data:', e);
            }
        }
    }
}

// ===== Initialize Auto-save on forms =====
document.addEventListener('DOMContentLoaded', function() {
    const forms = document.querySelectorAll('form[data-autosave]');
    forms.forEach(form => {
        const key = form.getAttribute('data-autosave') || 'form_data';
        new AutoSave(form.id, key);
    });
});

// ===== Print Report =====
function printReport() {
    window.print();
}

// ===== Export to CSV =====
function exportToCSV(data, filename) {
    const csv = data.map(row => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename + '.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

// ===== Toast Notifications =====
function showToast(title, message, type = 'success') {
    const colors = {
        success: '#28a745',
        error: '#dc3545',
        warning: '#ffc107',
        info: '#17a2b8'
    };
    
    const toast = document.createElement('div');
    toast.className = 'toast align-items-center text-white border-0';
    toast.style.backgroundColor = colors[type] || colors.info;
    toast.style.position = 'fixed';
    toast.style.bottom = '20px';
    toast.style.right = '20px';
    toast.style.zIndex = '9999';
    toast.style.minWidth = '300px';
    
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <strong>${title}</strong><br>
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    document.body.appendChild(toast);
    const bsToast = new bootstrap.Toast(toast, { delay: 5000 });
    bsToast.show();
    
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

// ===== API Helper =====
async function apiRequest(url, method = 'GET', data = null) {
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || ''
        }
    };
    
    if (data) {
        options.body = JSON.stringify(data);
    }
    
    try {
        const response = await fetch(url, options);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || 'API request failed');
        }
        return result;
    } catch (error) {
        console.error('API Error:', error);
        showToast('Error', error.message, 'error');
        throw error;
    }
}