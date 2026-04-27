-- TiShift OceanBase — Sample Schema (Oracle Mode)
--
-- Exercises OceanBase Oracle-mode features: NUMBER, VARCHAR2, DATE with time,
-- PL/SQL procedure, sequence, CONNECT BY view, ROWNUM, synonym, TABLEGROUP.

CREATE SEQUENCE dept_seq START WITH 100 INCREMENT BY 10;
CREATE SEQUENCE emp_seq START WITH 1000 INCREMENT BY 1;

CREATE TABLE departments (
    dept_id     NUMBER(4,0)    NOT NULL,
    dept_name   VARCHAR2(100)  NOT NULL,
    location    VARCHAR2(200),
    budget      NUMBER,
    created_at  DATE DEFAULT SYSDATE,
    CONSTRAINT dept_pk PRIMARY KEY (dept_id)
) TABLEGROUP = 'tg_hr';

CREATE TABLE employees (
    emp_id       NUMBER(10,0)   NOT NULL,
    first_name   VARCHAR2(50)   NOT NULL,
    last_name    VARCHAR2(50)   NOT NULL,
    email        VARCHAR2(100),
    hire_date    DATE           NOT NULL,
    salary       NUMBER(10,2),
    dept_id      NUMBER(4,0),
    manager_id   NUMBER(10,0),
    bio          CLOB,
    CONSTRAINT emp_pk PRIMARY KEY (emp_id),
    CONSTRAINT emp_dept_fk FOREIGN KEY (dept_id) REFERENCES departments(dept_id),
    CONSTRAINT emp_mgr_fk FOREIGN KEY (manager_id) REFERENCES employees(emp_id)
) TABLEGROUP = 'tg_hr';

CREATE SYNONYM emps FOR employees;

-- Stored procedure
CREATE OR REPLACE PROCEDURE add_employee(
    p_first_name IN VARCHAR2,
    p_last_name  IN VARCHAR2,
    p_salary     IN NUMBER,
    p_dept_id    IN NUMBER
) AS
BEGIN
    INSERT INTO employees (emp_id, first_name, last_name, hire_date, salary, dept_id)
    VALUES (emp_seq.NEXTVAL, p_first_name, p_last_name, SYSDATE, p_salary, p_dept_id);
    COMMIT;
END;
/

-- View with CONNECT BY
CREATE OR REPLACE VIEW org_tree AS
SELECT emp_id, first_name || ' ' || last_name AS full_name,
       manager_id, LEVEL AS depth
FROM employees
START WITH manager_id IS NULL
CONNECT BY PRIOR emp_id = manager_id;

-- View with ROWNUM
CREATE OR REPLACE VIEW top_earners AS
SELECT * FROM (
    SELECT emp_id, first_name, last_name, salary
    FROM employees ORDER BY salary DESC
) WHERE ROWNUM <= 10;

-- Sample data
INSERT INTO departments VALUES (10, 'Engineering', 'San Francisco', 5000000, SYSDATE);
INSERT INTO employees (emp_id, first_name, last_name, email, hire_date, salary, dept_id, manager_id)
VALUES (1, 'Alice', 'Chen', 'alice@example.com', TO_DATE('2020-03-15', 'YYYY-MM-DD'), 150000, 10, NULL);
INSERT INTO employees (emp_id, first_name, last_name, email, hire_date, salary, dept_id, manager_id)
VALUES (2, 'Bob', 'Kumar', 'bob@example.com', TO_DATE('2021-06-01', 'YYYY-MM-DD'), 120000, 10, 1);
COMMIT;
