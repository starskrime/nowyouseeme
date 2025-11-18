(function() {
    'use strict';

    // Get configuration from script tag
    var script = document.currentScript || document.querySelector('script[data-site-key]');
    if (!script) {
        console.error('Retention tracking: Script tag not found');
        return;
    }

    var SITE_KEY = script.getAttribute('data-site-key');
    if (!SITE_KEY) {
        console.error('Retention tracking: data-site-key attribute is required');
        return;
    }

    // Get the API endpoint from the script src or use relative path
    var scriptSrc = script.src;
    var API_BASE = scriptSrc ? scriptSrc.replace('/static/tracking/pixel.js', '') : '';
    var TRACK_ENDPOINT = API_BASE + '/api/track/';

    // Cookie helpers
    function getCookie(name) {
        var value = "; " + document.cookie;
        var parts = value.split("; " + name + "=");
        if (parts.length === 2) return parts.pop().split(";").shift();
    }

    function setCookie(name, value, days) {
        var expires = "";
        if (days) {
            var date = new Date();
            date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
            expires = "; expires=" + date.toUTCString();
        }
        document.cookie = name + "=" + (value || "") + expires + "; path=/; SameSite=Lax";
    }

    // Generate unique visitor ID
    function generateVisitorId() {
        return 'vis_' + Date.now() + '_' + Math.random().toString(36).substring(2, 15);
    }

    // Get or create visitor ID
    function getVisitorId() {
        var visitorId = getCookie('nowyouseeme_visitor_id');
        if (!visitorId) {
            visitorId = generateVisitorId();
            setCookie('nowyouseeme_visitor_id', visitorId, 180); // 6 months
        } else {
            // Refresh cookie lifetime on each visit
            setCookie('nowyouseeme_visitor_id', visitorId, 180);
        }
        return visitorId;
    }

    // Generate session ID
    function getSessionId() {
        var sessionId = sessionStorage.getItem('nowyouseeme_session_id');
        if (!sessionId) {
            sessionId = 'ses_' + Date.now() + '_' + Math.random().toString(36).substring(2, 15);
            sessionStorage.setItem('nowyouseeme_session_id', sessionId);
        }
        return sessionId;
    }

    var visitorId = getVisitorId();
    var sessionId = getSessionId();

    // Collect browser fingerprint data
    function getBrowserFingerprint() {
        var fingerprint = {};

        // Detect browser
        var ua = navigator.userAgent;
        fingerprint.user_agent = ua;

        // Browser detection
        if (ua.indexOf('Chrome') > -1 && ua.indexOf('Edge') === -1) {
            fingerprint.browser_name = 'Chrome';
        } else if (ua.indexOf('Safari') > -1 && ua.indexOf('Chrome') === -1) {
            fingerprint.browser_name = 'Safari';
        } else if (ua.indexOf('Firefox') > -1) {
            fingerprint.browser_name = 'Firefox';
        } else if (ua.indexOf('MSIE') > -1 || ua.indexOf('Trident') > -1) {
            fingerprint.browser_name = 'Internet Explorer';
        } else if (ua.indexOf('Edge') > -1) {
            fingerprint.browser_name = 'Edge';
        } else {
            fingerprint.browser_name = 'Unknown';
        }

        // OS detection
        if (ua.indexOf('Windows') > -1) {
            fingerprint.os_name = 'Windows';
        } else if (ua.indexOf('Mac') > -1) {
            fingerprint.os_name = 'MacOS';
        } else if (ua.indexOf('Linux') > -1) {
            fingerprint.os_name = 'Linux';
        } else if (ua.indexOf('Android') > -1) {
            fingerprint.os_name = 'Android';
        } else if (ua.indexOf('iOS') > -1 || ua.indexOf('iPhone') > -1 || ua.indexOf('iPad') > -1) {
            fingerprint.os_name = 'iOS';
        } else {
            fingerprint.os_name = 'Unknown';
        }

        // Device type
        if (/(tablet|ipad|playbook|silk)|(android(?!.*mobi))/i.test(ua)) {
            fingerprint.device_type = 'tablet';
        } else if (/Mobile|Android|iP(hone|od)|IEMobile|BlackBerry|Kindle|Silk-Accelerated|(hpw|web)OS|Opera M(obi|ini)/.test(ua)) {
            fingerprint.device_type = 'mobile';
        } else {
            fingerprint.device_type = 'desktop';
        }

        // Screen resolution
        fingerprint.screen_resolution = screen.width + 'x' + screen.height;

        // Timezone
        fingerprint.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

        // Language
        fingerprint.language = navigator.language || navigator.userLanguage;

        return fingerprint;
    }

    var browserFingerprint = getBrowserFingerprint();

    // Extract UTM parameters from URL
    function getUTMParameters() {
        var params = {};
        var urlParams = new URLSearchParams(window.location.search);

        params.utm_source = urlParams.get('utm_source') || null;
        params.utm_medium = urlParams.get('utm_medium') || null;
        params.utm_campaign = urlParams.get('utm_campaign') || null;
        params.utm_term = urlParams.get('utm_term') || null;
        params.utm_content = urlParams.get('utm_content') || null;

        return params;
    }

    // Store UTM parameters in cookie for first-touch attribution
    function storeUTMParameters() {
        var utmParams = getUTMParameters();
        var hasUTM = utmParams.utm_source || utmParams.utm_medium || utmParams.utm_campaign;

        if (hasUTM) {
            // Only store if this is the first visit or UTM params changed
            var storedUTM = getCookie('nowyouseeme_utm_params');
            if (!storedUTM) {
                setCookie('nowyouseeme_utm_params', JSON.stringify(utmParams), 30);
            }
        }

        return utmParams;
    }

    // Get stored UTM parameters for first-touch attribution
    function getStoredUTMParameters() {
        var stored = getCookie('nowyouseeme_utm_params');
        if (stored) {
            try {
                return JSON.parse(stored);
            } catch (e) {
                return {};
            }
        }
        return {};
    }

    var currentUTM = storeUTMParameters();
    var storedUTM = getStoredUTMParameters();

    // Store visitor/contact data from server responses
    var visitorData = {
        visitor_id: visitorId,
        session_id: sessionId,
        is_identified: false,
        contact: null,
        enrichment: null,
        browser: browserFingerprint,
        utm: currentUTM
    };

    // Track event function
    function trackEvent(eventType, eventData, callback) {
        eventData = eventData || {};

        // IMPORTANT: Never send is_identified or matched_via to the server
        // These fields are ALWAYS computed server-side and returned in the response
        // The server determines identification based on multi-factor matching
        var payload = {
            site_key: SITE_KEY,
            visitor_id: visitorId,
            session_id: sessionId,
            event_type: eventType,
            page_url: window.location.href,
            page_title: document.title,
            referrer: document.referrer,
            event_data: eventData,
            // Add browser fingerprint
            browser_fingerprint: browserFingerprint,
            // Add UTM parameters (both current and stored for first-touch)
            utm_params: currentUTM,
            stored_utm_params: storedUTM
        };

        // Send via navigator.sendBeacon if available (for page unload), otherwise XHR
        var data = JSON.stringify(payload);

        // Use XHR for better response handling
        var xhr = new XMLHttpRequest();
        xhr.open('POST', TRACK_ENDPOINT, true);
        xhr.setRequestHeader('Content-Type', 'application/json');

        xhr.onload = function() {
            if (xhr.status === 201) {
                try {
                    var response = JSON.parse(xhr.responseText);

                    // Update visitor data from server response
                    if (response.visitor) {
                        visitorData.is_identified = response.visitor.is_identified;
                        visitorData.matched_via = response.visitor.matched_via;
                        visitorData.browser = response.visitor.browser;
                    }

                    if (response.contact) {
                        visitorData.contact = response.contact;
                    }

                    if (response.enrichment) {
                        visitorData.enrichment = response.enrichment;
                    }

                    // Trigger custom event for personalization
                    if (response.visitor && response.visitor.is_identified) {
                        var identifiedEvent = new CustomEvent('nowyouseemeIdentified', {
                            detail: {
                                visitor: response.visitor,
                                contact: response.contact,
                                enrichment: response.enrichment
                            }
                        });
                        window.dispatchEvent(identifiedEvent);
                    }

                    // Call callback if provided
                    if (callback && typeof callback === 'function') {
                        callback(response);
                    }
                } catch (e) {
                    console.error('Error parsing tracking response:', e);
                }
            }
        };

        xhr.onerror = function() {
            console.error('Error sending tracking event');
        };

        xhr.send(data);
    }

    // Auto-track page view
    trackEvent('page_view', {
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
        screen_width: screen.width,
        screen_height: screen.height
    });

    // Auto-capture email from form inputs
    function setupEmailCapture() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', captureEmailFromForms);
        } else {
            captureEmailFromForms();
        }
    }

    function captureEmailFromForms() {
        // Find all email input fields
        var emailInputs = document.querySelectorAll('input[type="email"], input[name*="email" i], input[id*="email" i]');

        emailInputs.forEach(function(input) {
            // Listen for blur event (when user leaves the field)
            input.addEventListener('blur', function() {
                var email = input.value.trim();
                if (email && email.indexOf('@') > -1 && !visitorData.is_identified) {
                    // Send identify event
                    window.NowYouSeeMeTracker.identify(email, {
                        source: 'form_capture',
                        form_url: window.location.href
                    });
                }
            });

            // Also listen for change event
            input.addEventListener('change', function() {
                var email = input.value.trim();
                if (email && email.indexOf('@') > -1 && !visitorData.is_identified) {
                    window.NowYouSeeMeTracker.identify(email, {
                        source: 'form_capture',
                        form_url: window.location.href
                    });
                }
            });
        });
    }

    // Initialize email capture
    setupEmailCapture();

    // Expose global tracking API
    window.NowYouSeeMeTracker = {
        track: trackEvent,
        getVisitorId: function() { return visitorId; },
        getSessionId: function() { return sessionId; },

        // Get full visitor data including enrichment
        getVisitorData: function() { return visitorData; },

        // Check if visitor is identified
        isIdentified: function() { return visitorData.is_identified; },

        // Get contact information (if identified)
        getContact: function() { return visitorData.contact; },

        // Get enrichment data (if available)
        getEnrichment: function() { return visitorData.enrichment; },

        // Get browser fingerprint data
        getBrowser: function() { return visitorData.browser; },

        // Get matched via method (e.g., 'ip_address', 'email')
        getMatchMethod: function() { return visitorData.matched_via; },

        // Convenience methods for common events
        trackCartView: function(items) {
            trackEvent('cart_view', { items: items });
        },

        trackCartAdd: function(item) {
            trackEvent('cart_add', { item: item });
        },

        trackCheckoutStart: function(cart) {
            trackEvent('checkout_start', { cart: cart });
        },

        trackPurchase: function(order) {
            trackEvent('purchase', { order: order });
        },

        trackFormSubmit: function(formName, formData) {
            trackEvent('form_submit', {
                form_name: formName,
                form_data: formData
            });
        },

        // Identity resolution - associate visitor with email
        identify: function(email, userData) {
            userData = userData || {};
            userData.email = email;
            trackEvent('custom', {
                event_name: 'identify',
                identity_data: userData
            });
        },

        // Abandonment tracking
        trackBrowseAbandonment: function(pageData) {
            trackEvent('browse_abandonment', pageData || {
                page_url: window.location.href,
                page_title: document.title
            });
        },

        trackProductView: function(product) {
            trackEvent('product_view', {
                product: product,
                viewed_at: new Date().toISOString()
            });
        },

        trackProductAbandonment: function(product) {
            trackEvent('product_abandonment', {
                product: product,
                abandoned_at: new Date().toISOString()
            });
        },

        trackCartAbandonment: function(cart) {
            trackEvent('cart_abandonment', {
                cart: cart,
                abandoned_at: new Date().toISOString()
            });
        },

        trackCheckoutAbandonment: function(checkout) {
            trackEvent('checkout_abandonment', {
                checkout: checkout,
                abandoned_at: new Date().toISOString()
            });
        }
    };

    // Automatic abandonment detection
    var abandonmentTracking = {
        lastProductView: null,
        lastCartView: null,
        lastCheckoutView: null,
        abandonmentTimeout: 30000, // 30 seconds

        trackProductAbandonment: function(product) {
            var self = this;
            if (this.productTimer) clearTimeout(this.productTimer);

            this.lastProductView = product;
            this.productTimer = setTimeout(function() {
                if (self.lastProductView) {
                    window.NowYouSeeMeTracker.trackProductAbandonment(self.lastProductView);
                }
            }, this.abandonmentTimeout);
        },

        trackCartAbandonment: function(cart) {
            var self = this;
            if (this.cartTimer) clearTimeout(this.cartTimer);

            this.lastCartView = cart;
            this.cartTimer = setTimeout(function() {
                if (self.lastCartView) {
                    window.NowYouSeeMeTracker.trackCartAbandonment(self.lastCartView);
                }
            }, this.abandonmentTimeout);
        },

        trackCheckoutAbandonment: function(checkout) {
            var self = this;
            if (this.checkoutTimer) clearTimeout(this.checkoutTimer);

            this.lastCheckoutView = checkout;
            this.checkoutTimer = setTimeout(function() {
                if (self.lastCheckoutView) {
                    window.NowYouSeeMeTracker.trackCheckoutAbandonment(self.lastCheckoutView);
                }
            }, this.abandonmentTimeout);
        },

        clearProduct: function() {
            if (this.productTimer) clearTimeout(this.productTimer);
            this.lastProductView = null;
        },

        clearCart: function() {
            if (this.cartTimer) clearTimeout(this.cartTimer);
            this.lastCartView = null;
        },

        clearCheckout: function() {
            if (this.checkoutTimer) clearTimeout(this.checkoutTimer);
            this.lastCheckoutView = null;
        }
    };

    // Expose abandonment tracking helper
    window.NowYouSeeMeAbandonment = abandonmentTracking;

    // Click tracking - captures all clicks with element details
    function setupClickTracking() {
        document.addEventListener('click', function(event) {
            try {
                var element = event.target;

                // Get the clicked element's text content
                var elementText = element.textContent || element.innerText || '';
                elementText = elementText.trim().substring(0, 200); // Limit to 200 chars

                // Get element type and attributes
                var tagName = element.tagName.toLowerCase();
                var elementId = element.id || null;
                var elementClass = element.className || null;

                // Get element selector path
                var selectorPath = getElementPath(element);

                // Get href for links
                var href = null;
                if (tagName === 'a' && element.href) {
                    href = element.href;
                } else if (element.closest('a')) {
                    // Clicked on element inside a link
                    var parentLink = element.closest('a');
                    href = parentLink.href;
                    elementText = elementText || parentLink.textContent.trim().substring(0, 200);
                }

                // Get button type and value
                var buttonType = null;
                var buttonValue = null;
                if (tagName === 'button' || tagName === 'input') {
                    buttonType = element.type || null;
                    buttonValue = element.value || null;
                }

                // Get position on page
                var rect = element.getBoundingClientRect();
                var clickPosition = {
                    x: Math.round(event.clientX),
                    y: Math.round(event.clientY),
                    element_x: Math.round(rect.left),
                    element_y: Math.round(rect.top),
                    element_width: Math.round(rect.width),
                    element_height: Math.round(rect.height)
                };

                // Get parent context - capture text from containing block
                var parentContext = getParentContext(element);

                // Build click data
                var clickData = {
                    element_tag: tagName,
                    element_text: elementText,
                    element_id: elementId,
                    element_class: elementClass,
                    element_path: selectorPath,
                    href: href,
                    button_type: buttonType,
                    button_value: buttonValue,
                    position: clickPosition,
                    parent_context: parentContext,
                    page_url: window.location.href,
                    page_title: document.title,
                    timestamp: new Date().toISOString()
                };

                // Send click event
                trackEvent('custom', {
                    event_name: 'click',
                    click_data: clickData
                });

            } catch (error) {
                console.error('Click tracking error:', error);
            }
        }, true); // Use capture phase to catch all clicks
    }

    // Helper function to get parent context (text from containing blocks)
    function getParentContext(element) {
        var context = {
            immediate_parent: null,
            parent_text: null,
            parent_tag: null,
            parent_id: null,
            parent_class: null,
            container_text: null,
            data_attributes: {}
        };

        try {
            // Get immediate parent
            var parent = element.parentElement;
            if (parent) {
                context.parent_tag = parent.tagName.toLowerCase();
                context.parent_id = parent.id || null;
                context.parent_class = parent.className || null;

                // Get parent's direct text (excluding nested elements)
                var parentTextOnly = '';
                for (var i = 0; i < parent.childNodes.length; i++) {
                    var node = parent.childNodes[i];
                    if (node.nodeType === Node.TEXT_NODE) {
                        parentTextOnly += node.textContent;
                    }
                }
                context.parent_text = parentTextOnly.trim().substring(0, 300) || null;
            }

            // Look for common container patterns (card, product, item, block, etc.)
            var containers = ['card', 'product', 'item', 'block', 'panel', 'box', 'section'];
            var containerElement = null;

            for (var j = 0; j < containers.length; j++) {
                var containerClass = containers[j];
                containerElement = element.closest('.' + containerClass) ||
                                  element.closest('[class*="' + containerClass + '"]') ||
                                  element.closest('[data-' + containerClass + ']');
                if (containerElement) break;
            }

            // If found a container, get its full text content
            if (containerElement) {
                context.container_text = containerElement.textContent.trim().substring(0, 500);

                // Capture data attributes from container
                if (containerElement.dataset) {
                    for (var key in containerElement.dataset) {
                        if (containerElement.dataset.hasOwnProperty(key)) {
                            context.data_attributes[key] = containerElement.dataset[key];
                        }
                    }
                }
            } else {
                // Fallback: get parent's full text if no specific container found
                if (parent) {
                    context.container_text = parent.textContent.trim().substring(0, 500);
                }
            }

            // Also capture data attributes from the clicked element itself
            if (element.dataset) {
                for (var attrKey in element.dataset) {
                    if (element.dataset.hasOwnProperty(attrKey)) {
                        context.data_attributes['element_' + attrKey] = element.dataset[attrKey];
                    }
                }
            }

        } catch (error) {
            console.error('Error getting parent context:', error);
        }

        return context;
    }

    // Helper function to get element path (CSS selector path)
    function getElementPath(element) {
        if (!element) return '';

        var path = [];
        var current = element;

        while (current && current.nodeType === Node.ELEMENT_NODE && path.length < 5) {
            var selector = current.tagName.toLowerCase();

            if (current.id) {
                selector += '#' + current.id;
                path.unshift(selector);
                break; // ID is unique, stop here
            } else if (current.className) {
                var classes = current.className.trim().split(/\s+/).slice(0, 2).join('.');
                if (classes) {
                    selector += '.' + classes;
                }
            }

            path.unshift(selector);
            current = current.parentElement;
        }

        return path.join(' > ');
    }

    // Initialize click tracking after DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupClickTracking);
    } else {
        setupClickTracking();
    }

    console.log('Retention tracking initialized', {
        visitorId: visitorId,
        sessionId: sessionId,
        siteKey: SITE_KEY,
        clickTrackingEnabled: true
    });

})();
