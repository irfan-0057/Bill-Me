let selectedProduct = null;
let billItems = [];

document.getElementById('productSearch').addEventListener('input', function () {
    const query = this.value.toLowerCase();
    const dropdown = document.getElementById('productOptions');
    dropdown.innerHTML = '';

    if (query.length === 0) return;

    const matches = products.filter(p => p.name.toLowerCase().includes(query));

    matches.forEach(p => {
        const option = document.createElement('div');
        option.textContent = p.name + ' (' + p.company_name + ')';
        option.classList.add('dropdown-item');
        option.addEventListener('click', () => {
            selectedProduct = p;
            document.getElementById('productSearch').value = p.name;
            dropdown.innerHTML = '';
        });
        dropdown.appendChild(option);
    });
});

document.getElementById('addItemBtn').addEventListener('click', () => {
    const qty = parseFloat(document.getElementById('qtyInput').value);
    if (!selectedProduct || isNaN(qty) || qty <= 0) {
        alert('Please select a valid product and quantity.');
        return;
    }

    const gstRate = selectedProduct.gst_percentage || 0;
    const rate = selectedProduct.rate;
    const gstAmount = (rate * qty * gstRate) / 100;
    const total = rate * qty + gstAmount;

    const item = {
        name: selectedProduct.name,
        qty,
        rate,
        gstAmount,
        total
    };

    billItems.push(item);
    renderBill();
    clearForm();
});

function renderBill() {
    const tbody = document.getElementById('bill-items-body');
    tbody.innerHTML = '';

    let totalBeforeTax = 0;
    let totalGst = 0;
    let grandTotal = 0;

    billItems.forEach((item, index) => {
        totalBeforeTax += item.qty * item.rate;
        totalGst += item.gstAmount;
        grandTotal += item.total;

        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${item.name}</td>
            <td>${item.qty}</td>
            <td>${item.rate.toFixed(2)}</td>
            <td>${item.total.toFixed(2)}</td>
            <td><button onclick="removeItem(${index})">Remove</button></td>
        `;
        tbody.appendChild(row);
    });

    document.getElementById('totalBeforeTax').textContent = totalBeforeTax.toFixed(2);
    document.getElementById('totalGst').textContent = totalGst.toFixed(2);
    document.getElementById('grandTotal').textContent = grandTotal.toFixed(2);
}

function removeItem(index) {
    billItems.splice(index, 1);
    renderBill();
}

function clearForm() {
    selectedProduct = null;
    document.getElementById('productSearch').value = '';
    document.getElementById('qtyInput').value = '';
    document.getElementById('productOptions').innerHTML = '';
}
