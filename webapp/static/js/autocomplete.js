/**
 * Unified autocomplete functionality for text inputs.
 * 
 * This module provides autocomplete functionality for any input element
 * wrapped in an .autocomplete-wrapper with data-autocomplete-config attribute.
 * 
 * Usage:
 * 1. Include this script in your page
 * 2. Use the autocomplete_input.html template include
 * 3. Call initAutocomplete() after DOM is ready
 * 
 * Configuration (via data-autocomplete-config JSON):
 * - inputId: ID of the input element
 * - endpointUrl: API endpoint for suggestions
 * - displayField: Field name for display text (e.g., "name", "title")
 * - countField: Field name for count (optional, e.g., "count", "total_filings")
 * - slugField: Field name for navigation slug (optional)
 * - navigateUrlPattern: URL pattern with __slug__ placeholder (optional)
 * - submitOnSelect: Whether to submit parent form on selection (default: false)
 */

(function() {
    'use strict';
    
    const countFormatter = new Intl.NumberFormat('en-US');
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    function debounce(func, wait) {
        let timeout = null;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }
    
    class AutocompleteInput {
        constructor(wrapper) {
            this.wrapper = wrapper;
            this.config = JSON.parse(wrapper.dataset.autocompleteConfig || '{}');
            this.input = document.getElementById(this.config.inputId);
            this.dropdown = document.getElementById(this.config.inputId + '-autocomplete');
            this.currentSuggestions = [];
            this.selectedIndex = -1;
            
            if (!this.input || !this.dropdown) {
                console.warn('Autocomplete: Missing input or dropdown for', this.config.inputId);
                return;
            }
            
            this.init();
        }
        
        init() {
            // Input event for typing
            this.input.addEventListener('input', debounce((e) => {
                this.fetchSuggestions(e.target.value);
            }, 200));
            
            // Keyboard navigation
            this.input.addEventListener('keydown', (e) => this.handleKeydown(e));
            
            // Click outside to close
            document.addEventListener('click', (e) => {
                if (!this.input.contains(e.target) && !this.dropdown.contains(e.target)) {
                    this.hide();
                }
            });
            
            // Hide on form submit
            const form = this.input.closest('form');
            if (form) {
                form.addEventListener('submit', () => this.hide());
            }
        }
        
        async fetchSuggestions(query) {
            if (query.length < 2) {
                this.hide();
                return;
            }
            
            try {
                const response = await fetch(`${this.config.endpointUrl}?q=${encodeURIComponent(query)}`);
                if (!response.ok) {
                    throw new Error('Failed to fetch suggestions');
                }
                const suggestions = await response.json();
                this.currentSuggestions = suggestions;
                this.showSuggestions(suggestions, query);
            } catch (error) {
                console.error('Autocomplete fetch error:', error);
                this.hide();
            }
        }
        
        showSuggestions(suggestions, query) {
            if (!suggestions || suggestions.length === 0) {
                this.hide();
                return;
            }
            
            const queryLower = query.toLowerCase();
            const html = suggestions.map((suggestion, index) => {
                const displayText = suggestion[this.config.displayField] || '';
                const count = this.config.countField ? suggestion[this.config.countField] : null;
                
                // Format count label
                let countLabel = '';
                if (this.config.countField) {
                    if (count !== undefined && count !== null) {
                        countLabel = `${countFormatter.format(count)} filings`;
                    } else {
                        countLabel = '0 filings';
                    }
                }
                
                // Highlight matching text
                const matchIndex = displayText.toLowerCase().indexOf(queryLower);
                let displayHtml;
                
                if (matchIndex === -1) {
                    displayHtml = escapeHtml(displayText);
                } else {
                    const before = displayText.substring(0, matchIndex);
                    const match = displayText.substring(matchIndex, matchIndex + query.length);
                    const after = displayText.substring(matchIndex + query.length);
                    displayHtml = `${escapeHtml(before)}<strong>${escapeHtml(match)}</strong>${escapeHtml(after)}`;
                }
                
                const countHtml = countLabel ? `<span class="autocomplete-count">${countLabel}</span>` : '';
                
                return `<div class="autocomplete-item" data-index="${index}">${displayHtml}${countHtml}</div>`;
            }).join('');
            
            this.dropdown.innerHTML = html;
            this.dropdown.style.display = 'block';
            this.selectedIndex = -1;
            
            // Add click handlers
            this.dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
                item.addEventListener('click', () => {
                    const index = parseInt(item.dataset.index);
                    this.selectSuggestion(suggestions[index]);
                });
                
                item.addEventListener('mouseenter', () => {
                    this.selectedIndex = parseInt(item.dataset.index);
                    this.updateHighlight();
                });
            });
        }
        
        hide() {
            this.dropdown.style.display = 'none';
            this.currentSuggestions = [];
            this.selectedIndex = -1;
        }
        
        selectSuggestion(suggestion) {
            const displayText = suggestion[this.config.displayField] || '';
            this.input.value = displayText;
            this.hide();
            
            // Navigate if URL pattern is provided
            if (this.config.navigateUrlPattern && this.config.slugField) {
                const slug = suggestion[this.config.slugField];
                if (slug) {
                    const url = this.config.navigateUrlPattern.replace('__slug__', slug);
                    window.location.href = url;
                    return;
                }
            }
            
            // Submit form if configured
            if (this.config.submitOnSelect) {
                const form = this.input.closest('form');
                if (form) {
                    form.submit();
                }
            }
        }
        
        updateHighlight() {
            this.dropdown.querySelectorAll('.autocomplete-item').forEach((item, index) => {
                if (index === this.selectedIndex) {
                    item.classList.add('active');
                } else {
                    item.classList.remove('active');
                }
            });
        }
        
        handleKeydown(e) {
            if (this.dropdown.style.display === 'none' || this.currentSuggestions.length === 0) {
                return;
            }
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.selectedIndex = Math.min(this.selectedIndex + 1, this.currentSuggestions.length - 1);
                this.updateHighlight();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
                this.updateHighlight();
            } else if (e.key === 'Enter' && this.selectedIndex >= 0) {
                e.preventDefault();
                this.selectSuggestion(this.currentSuggestions[this.selectedIndex]);
            } else if (e.key === 'Escape') {
                this.hide();
            }
        }
    }
    
    // Initialize all autocomplete inputs on the page
    function initAutocomplete() {
        document.querySelectorAll('.autocomplete-wrapper[data-autocomplete-config]').forEach(wrapper => {
            new AutocompleteInput(wrapper);
        });
    }
    
    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAutocomplete);
    } else {
        initAutocomplete();
    }
    
    // Export for manual initialization if needed
    window.initAutocomplete = initAutocomplete;
    window.AutocompleteInput = AutocompleteInput;
})();
