-- =============================================================
-- OracleChat Demo Schema - E-Commerce
-- Oracle Database 19c
-- =============================================================

SET DEFINE OFF;
SET SQLBLANKLINES ON;

-- =============================================================
-- DROP TABLES
-- =============================================================
BEGIN
    FOR t IN (
        SELECT table_name FROM user_tables
        WHERE table_name IN (
            'PAYMENTS','ORDER_ITEMS','ORDERS','PRODUCTS','CUSTOMERS'
        )
    ) LOOP
        EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' CASCADE CONSTRAINTS';
    END LOOP;
END;
/

-- =============================================================
-- DROP SEQUENCES
-- =============================================================
BEGIN
    FOR s IN (
        SELECT sequence_name FROM user_sequences
        WHERE sequence_name IN (
            'SEQ_CUSTOMERS','SEQ_ORDERS','SEQ_PRODUCTS',
            'SEQ_ORDER_ITEMS','SEQ_PAYMENTS'
        )
    ) LOOP
        EXECUTE IMMEDIATE 'DROP SEQUENCE ' || s.sequence_name;
    END LOOP;
END;
/

-- =============================================================
-- SEQUENCES
-- =============================================================
CREATE SEQUENCE seq_customers START WITH 1 INCREMENT BY 1 NOCACHE NOCYCLE;
CREATE SEQUENCE seq_orders START WITH 1 INCREMENT BY 1 NOCACHE NOCYCLE;
CREATE SEQUENCE seq_products START WITH 1 INCREMENT BY 1 NOCACHE NOCYCLE;
CREATE SEQUENCE seq_order_items START WITH 1 INCREMENT BY 1 NOCACHE NOCYCLE;
CREATE SEQUENCE seq_payments START WITH 1 INCREMENT BY 1 NOCACHE NOCYCLE;

-- =============================================================
-- CUSTOMERS
-- =============================================================
CREATE TABLE customers (
    customer_id NUMBER DEFAULT seq_customers.NEXTVAL
        CONSTRAINT pk_customers PRIMARY KEY,

    first_name VARCHAR2(50) NOT NULL,
    last_name VARCHAR2(50) NOT NULL,

    email VARCHAR2(100) NOT NULL
        CONSTRAINT uq_customers_email UNIQUE,

    phone VARCHAR2(20),
    city VARCHAR2(60),
    country VARCHAR2(60) DEFAULT 'Morocco' NOT NULL,

    registration_date DATE DEFAULT SYSDATE NOT NULL,

    status VARCHAR2(15) DEFAULT 'ACTIVE' NOT NULL
        CONSTRAINT ck_customers_status
        CHECK (status IN ('ACTIVE','INACTIVE','BANNED'))
);

-- =============================================================
-- PRODUCTS
-- =============================================================
CREATE TABLE products (
    product_id NUMBER DEFAULT seq_products.NEXTVAL
        CONSTRAINT pk_products PRIMARY KEY,

    name VARCHAR2(150) NOT NULL,
    category VARCHAR2(60) NOT NULL,

    unit_price NUMBER(10,2) NOT NULL
        CONSTRAINT ck_products_price CHECK (unit_price > 0),

    stock_quantity NUMBER(10) DEFAULT 0 NOT NULL
        CONSTRAINT ck_products_stock CHECK (stock_quantity >= 0),

    status VARCHAR2(10) DEFAULT 'ACTIVE' NOT NULL
        CONSTRAINT ck_products_status
        CHECK (status IN ('ACTIVE','DISCONTINUED'))
);

-- =============================================================
-- ORDERS
-- =============================================================
CREATE TABLE orders (
    order_id NUMBER DEFAULT seq_orders.NEXTVAL
        CONSTRAINT pk_orders PRIMARY KEY,

    customer_id NUMBER NOT NULL
        CONSTRAINT fk_orders_customer
        REFERENCES customers(customer_id),

    order_date DATE DEFAULT SYSDATE NOT NULL,

    status VARCHAR2(20) DEFAULT 'PENDING' NOT NULL
        CONSTRAINT ck_orders_status
        CHECK (status IN (
            'PENDING','CONFIRMED','SHIPPED',
            'DELIVERED','CANCELLED','RETURNED'
        )),

    total_amount NUMBER(12,2) DEFAULT 0 NOT NULL
        CONSTRAINT ck_orders_total CHECK (total_amount >= 0),

    shipping_address VARCHAR2(255)
);

-- =============================================================
-- ORDER_ITEMS
-- =============================================================
CREATE TABLE order_items (
    item_id NUMBER DEFAULT seq_order_items.NEXTVAL
        CONSTRAINT pk_order_items PRIMARY KEY,

    order_id NUMBER NOT NULL
        CONSTRAINT fk_items_order
        REFERENCES orders(order_id),

    product_id NUMBER NOT NULL
        CONSTRAINT fk_items_product
        REFERENCES products(product_id),

    quantity NUMBER(5) NOT NULL
        CONSTRAINT ck_items_qty CHECK (quantity > 0),

    unit_price NUMBER(10,2) NOT NULL
        CONSTRAINT ck_items_price CHECK (unit_price > 0),

    line_total NUMBER(12,2) NOT NULL
        CONSTRAINT ck_items_total CHECK (line_total > 0),

    CONSTRAINT uq_order_product UNIQUE (order_id, product_id)
);

-- =============================================================
-- PAYMENTS
-- =============================================================
CREATE TABLE payments (
    payment_id NUMBER DEFAULT seq_payments.NEXTVAL
        CONSTRAINT pk_payments PRIMARY KEY,

    order_id NUMBER NOT NULL
        CONSTRAINT fk_payments_order
        REFERENCES orders(order_id),

    payment_date DATE DEFAULT SYSDATE NOT NULL,

    amount NUMBER(12,2) NOT NULL
        CONSTRAINT ck_payments_amount CHECK (amount > 0),

    method VARCHAR2(20) NOT NULL
        CONSTRAINT ck_payments_method
        CHECK (method IN (
            'CREDIT_CARD','DEBIT_CARD',
            'BANK_TRANSFER','CASH_ON_DELIVERY',
            'MOBILE_PAYMENT'
        )),

    status VARCHAR2(10) DEFAULT 'PENDING' NOT NULL
        CONSTRAINT ck_payments_status
        CHECK (status IN ('PENDING','COMPLETED','FAILED','REFUNDED'))
);

-- =============================================================
-- INDEXES
-- =============================================================
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
CREATE INDEX idx_payments_order ON payments(order_id);

CREATE INDEX idx_orders_date_status ON orders(order_date, status);
CREATE INDEX idx_products_category ON products(category, status);

COMMIT;