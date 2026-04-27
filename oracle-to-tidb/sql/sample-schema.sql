-- TiShift Oracle — Sample Schema for Demos and Tests
--
-- This schema exercises the key Oracle features that TiShift must handle:
-- tables, PKs, FKs, indexes, sequences, triggers, stored procedures,
-- a PL/SQL package, a view with CONNECT BY, CLOB column, NUMBER without
-- precision, DATE column, synonym, materialized view, and partitioning.

-- Sequences
CREATE SEQUENCE dept_seq START WITH 100 INCREMENT BY 10 CACHE 20;
CREATE SEQUENCE emp_seq START WITH 1000 INCREMENT BY 1 CACHE 20;
CREATE SEQUENCE order_seq START WITH 1 INCREMENT BY 1 CACHE 50;

-- Departments
CREATE TABLE departments (
    dept_id     NUMBER(4,0)    NOT NULL,
    dept_name   VARCHAR2(100)  NOT NULL,
    location    VARCHAR2(200),
    budget      NUMBER,  -- no precision — TiShift must handle this
    created_at  DATE     DEFAULT SYSDATE,  -- Oracle DATE includes time
    CONSTRAINT dept_pk PRIMARY KEY (dept_id)
);

-- Employees
CREATE TABLE employees (
    emp_id       NUMBER(10,0)   NOT NULL,
    first_name   VARCHAR2(50)   NOT NULL,
    last_name    VARCHAR2(50)   NOT NULL,
    email        VARCHAR2(100),
    hire_date    DATE           NOT NULL,
    salary       NUMBER(10,2),
    dept_id      NUMBER(4,0),
    manager_id   NUMBER(10,0),
    bio          CLOB,  -- LOB column
    CONSTRAINT emp_pk PRIMARY KEY (emp_id),
    CONSTRAINT emp_dept_fk FOREIGN KEY (dept_id) REFERENCES departments(dept_id),
    CONSTRAINT emp_mgr_fk FOREIGN KEY (manager_id) REFERENCES employees(emp_id)
);

CREATE INDEX emp_dept_idx ON employees(dept_id);
CREATE INDEX emp_name_idx ON employees(last_name, first_name);
CREATE UNIQUE INDEX emp_email_idx ON employees(email);

-- Orders (partitioned by date range)
CREATE TABLE orders (
    order_id    NUMBER(12,0)  NOT NULL,
    emp_id      NUMBER(10,0)  NOT NULL,
    order_date  DATE          NOT NULL,
    total       NUMBER(12,2),
    status      VARCHAR2(20)  DEFAULT 'PENDING',
    notes       VARCHAR2(4000),
    CONSTRAINT order_pk PRIMARY KEY (order_id),
    CONSTRAINT order_emp_fk FOREIGN KEY (emp_id) REFERENCES employees(emp_id)
)
PARTITION BY RANGE (order_date) (
    PARTITION orders_2023 VALUES LESS THAN (TO_DATE('2024-01-01', 'YYYY-MM-DD')),
    PARTITION orders_2024 VALUES LESS THAN (TO_DATE('2025-01-01', 'YYYY-MM-DD')),
    PARTITION orders_2025 VALUES LESS THAN (TO_DATE('2026-01-01', 'YYYY-MM-DD')),
    PARTITION orders_future VALUES LESS THAN (MAXVALUE)
);

-- Synonym
CREATE SYNONYM emps FOR employees;

-- Trigger: auto-assign emp_id from sequence
CREATE OR REPLACE TRIGGER emp_before_insert
BEFORE INSERT ON employees
FOR EACH ROW
BEGIN
    IF :NEW.emp_id IS NULL THEN
        :NEW.emp_id := emp_seq.NEXTVAL;
    END IF;
END;
/

-- Stored procedure: simple (< 30 lines, no cursors)
CREATE OR REPLACE PROCEDURE add_employee(
    p_first_name IN VARCHAR2,
    p_last_name  IN VARCHAR2,
    p_email      IN VARCHAR2,
    p_salary     IN NUMBER,
    p_dept_id    IN NUMBER
) AS
BEGIN
    INSERT INTO employees (emp_id, first_name, last_name, email, hire_date, salary, dept_id)
    VALUES (emp_seq.NEXTVAL, p_first_name, p_last_name, p_email, SYSDATE, p_salary, p_dept_id);
    COMMIT;
END;
/

-- Stored procedure: moderate (cursor + CONNECT BY pattern in logic)
CREATE OR REPLACE PROCEDURE list_subordinates(
    p_manager_id IN NUMBER
) AS
    CURSOR c_subs IS
        SELECT emp_id, first_name, last_name, manager_id, LEVEL AS depth
        FROM employees
        START WITH emp_id = p_manager_id
        CONNECT BY PRIOR emp_id = manager_id;
BEGIN
    FOR rec IN c_subs LOOP
        DBMS_OUTPUT.PUT_LINE(
            LPAD(' ', (rec.depth - 1) * 2) ||
            rec.first_name || ' ' || rec.last_name ||
            ' (ID: ' || rec.emp_id || ')'
        );
    END LOOP;
END;
/

-- PL/SQL Package: spec + body (2 procedures)
CREATE OR REPLACE PACKAGE dept_mgmt AS
    PROCEDURE create_department(p_name IN VARCHAR2, p_location IN VARCHAR2);
    FUNCTION get_department_budget(p_dept_id IN NUMBER) RETURN NUMBER;
END dept_mgmt;
/

CREATE OR REPLACE PACKAGE BODY dept_mgmt AS

    PROCEDURE create_department(p_name IN VARCHAR2, p_location IN VARCHAR2) IS
        v_dept_id NUMBER;
    BEGIN
        v_dept_id := dept_seq.NEXTVAL;
        INSERT INTO departments (dept_id, dept_name, location, created_at)
        VALUES (v_dept_id, p_name, p_location, SYSDATE);
        COMMIT;
    END create_department;

    FUNCTION get_department_budget(p_dept_id IN NUMBER) RETURN NUMBER IS
        v_budget NUMBER;
    BEGIN
        SELECT budget INTO v_budget
        FROM departments
        WHERE dept_id = p_dept_id;
        RETURN NVL(v_budget, 0);
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RETURN -1;
    END get_department_budget;

END dept_mgmt;
/

-- View with CONNECT BY hierarchical query
CREATE OR REPLACE VIEW org_tree AS
SELECT emp_id, first_name || ' ' || last_name AS full_name,
       manager_id, LEVEL AS depth,
       SYS_CONNECT_BY_PATH(last_name, '/') AS path
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR emp_id = manager_id;

-- View with ROWNUM (pagination pattern)
CREATE OR REPLACE VIEW top_earners AS
SELECT * FROM (
    SELECT emp_id, first_name, last_name, salary
    FROM employees
    ORDER BY salary DESC
) WHERE ROWNUM <= 10;

-- Materialized view with refresh
CREATE MATERIALIZED VIEW dept_summary
BUILD IMMEDIATE
REFRESH COMPLETE ON DEMAND
AS
SELECT d.dept_id, d.dept_name,
       COUNT(e.emp_id) AS emp_count,
       NVL(SUM(e.salary), 0) AS total_salary,
       NVL(AVG(e.salary), 0) AS avg_salary
FROM departments d
LEFT JOIN employees e ON d.dept_id = e.dept_id
GROUP BY d.dept_id, d.dept_name;

-- Sample data
INSERT INTO departments VALUES (10, 'Engineering', 'San Francisco', 5000000, SYSDATE);
INSERT INTO departments VALUES (20, 'Marketing', 'New York', 2000000, SYSDATE);
INSERT INTO departments VALUES (30, 'Finance', 'Chicago', 3000000, SYSDATE);

INSERT INTO employees (emp_id, first_name, last_name, email, hire_date, salary, dept_id, manager_id)
VALUES (1, 'Alice', 'Chen', 'alice.chen@example.com', TO_DATE('2020-03-15', 'YYYY-MM-DD'), 150000, 10, NULL);
INSERT INTO employees (emp_id, first_name, last_name, email, hire_date, salary, dept_id, manager_id)
VALUES (2, 'Bob', 'Kumar', 'bob.kumar@example.com', TO_DATE('2021-06-01', 'YYYY-MM-DD'), 120000, 10, 1);
INSERT INTO employees (emp_id, first_name, last_name, email, hire_date, salary, dept_id, manager_id)
VALUES (3, 'Carol', 'Santos', 'carol.santos@example.com', TO_DATE('2022-01-10', 'YYYY-MM-DD'), 130000, 20, 1);
INSERT INTO employees (emp_id, first_name, last_name, email, hire_date, salary, dept_id, manager_id)
VALUES (4, 'David', 'Park', 'david.park@example.com', TO_DATE('2022-08-20', 'YYYY-MM-DD'), 95000, 10, 2);

INSERT INTO orders (order_id, emp_id, order_date, total, status)
VALUES (1, 2, TO_DATE('2024-03-15', 'YYYY-MM-DD'), 5000.00, 'COMPLETED');
INSERT INTO orders (order_id, emp_id, order_date, total, status)
VALUES (2, 3, TO_DATE('2025-01-20', 'YYYY-MM-DD'), 12500.50, 'PENDING');

COMMIT;
