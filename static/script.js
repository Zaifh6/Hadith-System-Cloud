// Initialize narrator modal functionality when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initNarratorLinks();
    initModalTabs();
});

// Make narrator names clickable and open modal
function initNarratorLinks() {
    const narratorLinks = document.querySelectorAll('.narrator-link');
    const modal = document.getElementById('narrator-modal');
    const closeBtn = document.querySelector('.close-modal');
    const tabs = document.querySelectorAll('.modal-tab');
    const tabContents = document.querySelectorAll('.modal-tab-content');
    const modalTitle = document.querySelector('.modal-title');
    
    // Open modal when narrator is clicked
    narratorLinks.forEach(link => {
        link.addEventListener('click', function() {
            const narratorName = this.textContent.trim();
            modalTitle.textContent = narratorName;
            
            // Here you would load narrator data
            // For now, we're just opening an empty modal with the narrator's name
            
            modal.style.display = 'block';
            document.body.style.overflow = 'hidden'; // Prevent scrolling when modal is open
            activateTab(tabs[0], tabContents[0]);
        });
    });
    
    // Close modal when X is clicked
    closeBtn.addEventListener('click', function() {
        closeModal();
    });
    
    // Close modal when clicking outside
    window.addEventListener('click', function(event) {
        if (event.target === modal) {
            closeModal();
        }
    });
    
    // Close modal with ESC key
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape' && modal.style.display === 'block') {
            closeModal();
        }
    });
    
    function closeModal() {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto'; // Restore scrolling
    }
}

// Initialize tab switching in the modal
function initModalTabs() {
    const tabs = document.querySelectorAll('.modal-tab');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const targetId = this.getAttribute('data-tab');
            
            // Toggle active class for tabs
            document.querySelectorAll('.modal-tab').forEach(t => {
                t.classList.remove('active');
            });
            this.classList.add('active');
            
            // Toggle visibility of tab content
            document.querySelectorAll('.modal-tab-content').forEach(content => {
                content.classList.remove('active');
            });
            document.getElementById(targetId).classList.add('active');
        });
    });
}

// Helper function to activate a tab and its content
function activateTab(tab, content) {
    tab.classList.add('active');
    content.classList.add('active');
} 