<!-- a1cb752f-8d9b-447e-93a4-ec3da2332711 0b01de0a-28f8-4579-af08-9ea653c28485 -->
# Add FAQ, About, and Contact Pages

I will create three new pages to address user questions and provide site information, and add a navigation menu to the main layout.

## 1. Create Page Templates

- Create `webapp/templates/webapp/faq.html`:
- Include questions derived from common Reddit inquiries (PERM vs Visa Bulletin, Retrogression, Final Action vs Filing Dates).
- Use Bootstrap accordion for compact display.
- Create `webapp/templates/webapp/about.html`:
- Explain the tool's purpose, data source (State Dept), and projection methodology.
- Create `webapp/templates/webapp/contact.html`:
- Simple page with contact email and GitHub link.

## 2. Update Views and URLs

- **`webapp/views.py`**: Add `faq_view`, `about_view`, and `contact_view`.
- **`webapp/urls.py`**: Add paths for `faq/`, `about/`, and `contact/`.

## 3. Update Navigation (Compact)

- **`webapp/templates/webapp/base.html`**:
- Add a simple navigation bar in the header (right-aligned) with links: Home, FAQ, About, Contact.
- Ensure it's responsive (collapses on mobile).

## 4. Main Page Enhancements

- **`webapp/templates/webapp/dashboard.html`**:
- Add a "Freqently Asked Questions" call-to-action link near the "About This Dashboard" section pointing to the new FAQ page.