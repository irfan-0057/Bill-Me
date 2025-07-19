// File: backend/static/reports.js

document.addEventListener('DOMContentLoaded', function() {
    const generateBtn = document.getElementById('generate-report-btn');
    const reportTableBody = document.querySelector('#report-table tbody');

    generateBtn.addEventListener('click', async function() {
        const reportType = document.getElementById('report-type').value;
        const startDate = document.getElementById('start-date').value;
        const endDate = document.getElementById('end-date').value;
        const product = document.getElementById('product-select').value;
        
        if (!startDate || !endDate) {
            alert('Please select both a start and end date.');
            return;
        }

        try {
            const response = await fetch(`/sales_report?type=${reportType}&start_date=${startDate}&end_date=${endDate}&product=${product}`);
            const data = await response.json();
            
            if (response.ok) {
                renderReport(data, reportType);
            } else {
                console.error('Error fetching report:', data.error);
            }
        } catch (error) {
            console.error('An unexpected error occurred:', error);
        }
    });

    function renderReport(data, reportType) {
        reportTableBody.innerHTML = '';
        data.forEach(row => {
            const newRow = document.createElement('tr');
            let dateCell = row.date;
            if (reportType === 'monthly') {
                dateCell = row.period;
            } else if (reportType === 'yearly') {
                dateCell = row.period.substring(0, 4);
            }
            newRow.innerHTML = `
                <td>${dateCell}</td>
                <td>${row.product_name || 'All'}</td>
                <td>₹${row.total_sales.toFixed(2)}</td>
            `;
            reportTableBody.appendChild(newRow);
        });
    }
});