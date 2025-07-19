// File: static/billing.js

document.addEventListener('DOMContentLoaded', function() {
    let itemCounter = 0;
    const billItemsTableBody = document.querySelector('#bill-items-table tbody');
    const addItemBtn = document.getElementById('add-item-btn');
    const generateBillBtn = document.getElementById('generate-bill-btn');
    const grandTotalSpan = document.getElementById('grandTotal');
    const totalBeforeTaxSpan = document.getElementById('totalBeforeTax');
    const totalGstSpan = document.getElementById('totalGst');

    // Function to calculate and update totals
    function updateTotals() {
        let grandTotal = 0;
        let totalBeforeTax = 0;
        let totalGst = 0;

        document.querySelectorAll('.item-row').forEach(row => {
            const qty = parseFloat(row.querySelector('.qty-input').value) || 0;
            const rate = parseFloat(row.querySelector('.rate-input').value) || 0;
            const gstPercentage = parseFloat(row.querySelector('.gst-input').value) || 0;

            const amountBeforeTax = qty * rate;
            const gstAmount = amountBeforeTax * (gstPercentage / 100);
            const totalAmount = amountBeforeTax + gstAmount;

            row.querySelector('.amount-input').value = totalAmount.toFixed(2);
            
            totalBeforeTax += amountBeforeTax;
            totalGst += gstAmount;
            grandTotal += totalAmount;
        });

        totalBeforeTaxSpan.textContent = totalBeforeTax.toFixed(2);
        totalGstSpan.textContent = totalGst.toFixed(2);
        grandTotalSpan.textContent = grandTotal.toFixed(2);
    }

    // Function to fetch product details
    async function fetchProductDetails(productId, row) {
        if (!productId) return;
        try {
            const response = await fetch(`/product/${productId}`);
            if (!response.ok) {
                throw new Error('Product not found');
            }
            const product = await response.json();
            
            row.querySelector('.company-name').value = product.company_name || 'N/A';
            row.querySelector('.mfg-date').value = product.mfg_date || 'N/A';
            row.querySelector('.exp-date').value = product.exp_date || 'N/A';
            row.querySelector('.batch-num').value = product.batch_num || 'N/A';
            row.querySelector('.rate-input').value = product.rate.toFixed(2) || 0;
            row.querySelector('.gst-input').value = product.gst_percentage || 0;

            updateTotals();
        } catch (error) {
            console.error("Error fetching product details:", error);
        }
    }

    // Function to add a new item row
    function addItemRow() {
        itemCounter++;
        const newRow = document.createElement('tr');
        newRow.classList.add('item-row');
        newRow.innerHTML = `
            <td>
                <select class="product-select" required>
                    <option value="">Select Product</option>
                    ${products.map(p => `<option value="${p.id}">${p.name}</option>`).join('')}
                </select>
            </td>
            <td><input type="text" class="company-name" disabled></td>
            <td><input type="text" class="mfg-date" disabled></td>
            <td><input type="text" class="exp-date" disabled></td>
            <td><input type="text" class="batch-num" disabled></td>
            <td><input type="number" step="0.01" class="rate-input" disabled></td>
            <td><input type="number" class="qty-input" min="1" required></td>
            <td><input type="number" step="0.01" class="gst-input" disabled></td>
            <td><input type="number" step="0.01" class="amount-input" disabled></td>
            <td><button class="remove-item-btn">Remove</button></td>
        `;
        billItemsTableBody.appendChild(newRow);

        const productSelect = newRow.querySelector('.product-select');
        productSelect.addEventListener('change', (e) => {
            fetchProductDetails(e.target.value, newRow);
        });

        const qtyInput = newRow.querySelector('.qty-input');
        qtyInput.addEventListener('input', updateTotals);

        const removeItemBtn = newRow.querySelector('.remove-item-btn');
        removeItemBtn.addEventListener('click', () => {
            newRow.remove();
            updateTotals();
        });

        updateTotals();
    }

    addItemBtn.addEventListener('click', addItemRow);

    generateBillBtn.addEventListener('click', async () => {
        const customerName = document.getElementById('customerName').value;
        const village = document.getElementById('village').value;
        const mobileNum = document.getElementById('mobileNum').value;
        const billDate = document.getElementById('billDate').value;
        const grandTotal = parseFloat(grandTotalSpan.textContent);
        const totalBeforeTax = parseFloat(totalBeforeTaxSpan.textContent);
        const totalGst = parseFloat(totalGstSpan.textContent);
        
        if (!customerName || !village || !mobileNum || !billDate || grandTotal === 0) {
            alert('Please fill in all customer details and add at least one item.');
            return;
        }

        const billItems = [];
        document.querySelectorAll('.item-row').forEach(row => {
            const productId = row.querySelector('.product-select').value;
            const productName = row.querySelector('.product-select').options[row.querySelector('.product-select').selectedIndex].text;
            const companyName = row.querySelector('.company-name').value;
            const mfgDate = row.querySelector('.mfg-date').value;
            const expDate = row.querySelector('.exp-date').value;
            const batchNum = row.querySelector('.batch-num').value;
            const rate = parseFloat(row.querySelector('.rate-input').value);
            const qty = parseInt(row.querySelector('.qty-input').value);
            const gst = parseFloat(row.querySelector('.gst-input').value);
            const amount = parseFloat(row.querySelector('.amount-input').value);

            if (productId && qty > 0) {
                billItems.push({
                    name: productName,
                    company_name: companyName,
                    mfg_date: mfgDate,
                    exp_date: expDate,
                    batch_num: batchNum,
                    rate: rate,
                    qty: qty,
                    gst: gst,
                    amount: amount
                });
            }
        });

        if (billItems.length === 0) {
            alert('Please add at least one item to the bill.');
            return;
        }

        const billData = {
            customerName: customerName,
            village: village,
            mobile_num: mobileNum,
            billDate: billDate,
            totalBeforeTax: totalBeforeTax,
            totalGst: totalGst,
            grandTotal: grandTotal,
            products: billItems
        };

        try {
            const response = await fetch('/generate_pdf', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(billData)
            });

            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = `bill_${billDate}.pdf`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
            } else {
                console.error("Failed to generate PDF");
                alert("Failed to generate PDF. Please try again.");
            }
        } catch (error) {
            console.error("Error:", error);
            alert("An error occurred. Please check the console for details.");
        }
    });

    addItemRow(); // Add the first row on page load
});