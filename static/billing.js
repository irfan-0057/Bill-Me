document.addEventListener('DOMContentLoaded', function () {
    const productSearchInput = document.getElementById('productSearch');
    const productOptionsDiv = document.getElementById('productOptions');
    const qtyInput = document.getElementById('qtyInput');
    const addItemBtn = document.getElementById('addItemBtn');
    const billItemsBody = document.getElementById('bill-items-body');
    const totalBeforeTaxEl = document.getElementById('totalBeforeTax');
    const totalGstEl = document.getElementById('totalGst');
    const grandTotalEl = document.getElementById('grandTotal');
    const generateBillBtn = document.getElementById('generateBillBtn');
    const customerNameInput = document.getElementById('customerName');
    const billDateInput = document.getElementById('billDate');
    const villageInput = document.getElementById('village');
    const mobileNumInput = document.getElementById('mobileNum');

    let billItems = [];
    let itemCounter = 1;
    let selectedProductId = null;

    function renderSearchableOptions(filteredProducts) {
        productOptionsDiv.innerHTML = '';
        filteredProducts.forEach(product => {
            const optionDiv = document.createElement('div');
            optionDiv.textContent = `${product[1]} (${product[2]})`;
            optionDiv.dataset.id = product[0];
            optionDiv.addEventListener('click', () => {
                productSearchInput.value = optionDiv.textContent;
                selectedProductId = optionDiv.dataset.id;
                productOptionsDiv.style.display = 'none';
            });
            productOptionsDiv.appendChild(optionDiv);
        });
    }

    productSearchInput.addEventListener('focus', () => {
        renderSearchableOptions(products);
        productOptionsDiv.style.display = 'block';
    });

    productSearchInput.addEventListener('input', () => {
        const searchTerm = productSearchInput.value.toLowerCase();
        const filteredProducts = products.filter(product =>
            product[1].toLowerCase().includes(searchTerm) ||
            product[2].toLowerCase().includes(searchTerm)
        );
        renderSearchableOptions(filteredProducts);
        productOptionsDiv.style.display = 'block';
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.searchable-select-container')) {
            productOptionsDiv.style.display = 'none';
        }
    });

    addItemBtn.addEventListener('click', async () => {
        const qty = parseInt(qtyInput.value, 10);
        if (!selectedProductId || qty <= 0) {
            alert('Please select a product and enter a valid quantity.');
            return;
        }

        try {
            const response = await fetch(`/product/${selectedProductId}`);
            const product = await response.json();

            if (!response.ok) {
                alert(product.error);
                return;
            }

            if (product.stock_qty < qty) {
                alert(`Not enough stock. Only ${product.stock_qty} available.`);
                return;
            }

            const amount = product.rate * qty;
            const newItem = {
                id: itemCounter++,
                name: product.name,
                company_name: product.company_name,
                mfg_date: product.mfg_date,
                exp_date: product.exp_date,
                batch_num: product.batch_num,
                pack_size: product.pack_size,
                rate: product.rate,
                qty: qty,
                gst: product.gst_percentage,
                amount: parseFloat(amount)
            };

            billItems.push(newItem);
            renderBillItems();
            updateTotals();
            productSearchInput.value = '';
            selectedProductId = null;
            qtyInput.value = 1;
        } catch (error) {
            console.error('Error adding item:', error);
            alert('An error occurred while fetching product details.');
        }
    });

    function renderBillItems() {
        billItemsBody.innerHTML = '';
        billItems.forEach((item, index) => {
            const row = billItemsBody.insertRow();
            row.dataset.id = item.id;
            row.innerHTML = `
                <td>${index + 1}</td>
                <td>${item.name}</td>
                <td>${item.company_name}</td>
                <td>${item.qty}</td>
                <td>₹${item.rate.toFixed(2)}</td>
                <td>₹${item.amount.toFixed(2)}</td>
                <td><button class="button danger remove-item-btn">Remove</button></td>
            `;
        });

        document.querySelectorAll('.remove-item-btn').forEach(button => {
            button.addEventListener('click', (event) => {
                const row = event.target.closest('tr');
                const itemId = parseInt(row.dataset.id, 10);
                billItems = billItems.filter(item => item.id !== itemId);
                renderBillItems();
                updateTotals();
            });
        });
    }

    function updateTotals() {
        let totalBeforeTax = 0;
        let totalGst = 0;
        let grandTotal = 0;

        billItems.forEach(item => {
            grandTotal += item.amount;
            const basePrice = item.rate / (1 + item.gst / 100);
            const gstAmountPerItem = item.rate - basePrice;

            totalBeforeTax += basePrice * item.qty;
            totalGst += gstAmountPerItem * item.qty;
        });

        totalBeforeTaxEl.textContent = totalBeforeTax.toFixed(2);
        totalGstEl.textContent = totalGst.toFixed(2);
        grandTotalEl.textContent = grandTotal.toFixed(2);
    }

    generateBillBtn.addEventListener('click', async () => {
        if (billItems.length === 0) {
            alert('Please add at least one item to the bill.');
            return;
        }

        const billData = {
            customerName: customerNameInput.value,
            billDate: billDateInput.value,
            village: villageInput.value,
            mobileNum: mobileNumInput.value,
            products: billItems,
            totalBeforeTax: parseFloat(totalBeforeTaxEl.textContent),
            totalGst: parseFloat(totalGstEl.textContent),
            grandTotal: parseFloat(grandTotalEl.textContent)
        };

        try {
            const response = await fetch('/generate_pdf', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(billData)
            });

            const result = await response.json();

            if (response.ok) {
                window.open(`/serve_pdf/${result.filename}`, '_blank');
            } else {
                alert(`Error generating PDF: ${result.error}`);
            }
        } catch (error) {
            console.error('Error generating bill:', error);
            alert('An error occurred while generating the bill.');
        }
    });
});
