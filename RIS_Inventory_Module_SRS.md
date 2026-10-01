# System Requirements Specification (SRS)
## Radiology Information System (RIS) - Inventory Management Module
**Author:** RIS Engineering Architecture Team  
**Date:** August 2026  
**Document Version:** 1.0.0  

---

## 1. Document Overview & Scope

### 1.1 Purpose
This document specifies the software requirements for an embedded Inventory Management Module within a clinical Radiology Information System (RIS). It provides a technical blueprint for architects, database administrators, and developers to build, test, and integrate the system into existing imaging workflows.

### 1.2 Product Scope
The RIS Inventory Module adds native control over radiological consumables (e.g., contrast media, radioactive isotopes, catheters, specialized needles, IV kits, and personal protective equipment). Unlike standalone enterprise resource planning (ERP) applications, this engine natively integrates with DICOM/HL7 transaction states, ensuring zero-overhead workflow automation during real-time diagnostic and interventional studies.

### 1.3 Intended Audience
* Software Engineers / Full-Stack Developers
* Database Administrators (DBAs)
* Healthcare Systems Integrators (HL7/FHIR Engine Engineers)
* Quality Assurance (QA) / Clinical Validation Specialists

---

## 2. Architectural Design & Workflow Integration

### 2.1 The Core Inventory State Machine
To guarantee high consistency and avoid race conditions across multiple high-volume scanning suites, inventory states must shift automatically along the clinical worklist lifecycle:

```
[HL7 ORM / Order Placed] 
         │
         ▼
 1. ALLOCATE STOCK (State: Reserved) 
    - Maps Procedure Code (CPT) to standard item kit templates.
    - Soft-deducts items from specific Scanning Room ID inventory pools.
         │
         ▼
[PACS MPPS / Study Completed]
         │
         ▼
 2. CONSUME STOCK (State: Deducted)
    - Hard-deducts inventory totals via append-only ledger entries.
    - Triggers check against Par-Level limits.
         │
         ▼
 3. BILL & SYNC TRANSACTION
    - Fires HL7 DFT^P03 financial message to Hospital EHR.
    - Enqueues ERP sync hook for depleted items.
```

### 2.2 System Interoperability Architecture
The module relies on a tight three-way bridge to ensure clinical, logistical, and financial synchronicity:

```
┌────────────────────────┐         ┌────────────────────────┐
│     Radiology RIS      │         │   Hospital ERP Core    │
│  (Scheduler & Worklist)│         │ (Supply Chain/Logistics│
└───────────┬────────────┘         └───────────┬────────────┘
            │                                  │
            │ REST / WebSockets                │ HL7 MFN / REST
            ▼                                  ▼
┌───────────────────────────────────────────────────────────┐
│              RIS INVENTORY TRANSACTION ENGINE             │
│   (State Machine, Rules Engine, Append-only Ledger)       │
└───────────────────────────┬───────────────────────────────┘
                            │
                            │ HL7 DFT^P03 Message
                            ▼
               ┌────────────────────────┐
               │  Hospital EHR Billing  │
               │   (Chargemaster Matrix)│
               └────────────────────────┘
```

---

## 3. Database Schema Design (Core Relational Entities)

The database layer requires an append-only architecture for transaction history to ensure audit compliance, high transactional performance, and data integrity.

### 3.1 Entity Relationship Diagram (Conceptual Layout)
* `ItemMaster` (1) ─── (0..*) `LotDetail`
* `LotDetail` (1) ─── (0..*) `StockLedger`
* `LocationHierarchy` (1) ─── (0..*) `StockLedger`

### 3.2 SQL Table Definitions

```sql
-- 1. ITEM MASTER TABLE (Static SKU Information)
CREATE TABLE ItemMaster (
    item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku_id VARCHAR(50) UNIQUE NOT NULL,
    description VARCHAR(255) NOT NULL,
    manufacturer VARCHAR(100) NOT NULL,
    unit_cost DECIMAL(10, 2) NOT NULL,
    charge_code_hcpcs VARCHAR(20), -- Directly ties to patient billing bills
    is_hazardous BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. LOT DETAIL TABLE (Traceability & Expiration tracking)
CREATE TABLE LotDetail (
    lot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id UUID REFERENCES ItemMaster(item_id) ON DELETE RESTRICT,
    lot_number VARCHAR(50) NOT NULL,
    expiration_date DATE NOT NULL,
    serial_number VARCHAR(100), -- For high-value implantables/stents
    received_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_item_lot UNIQUE(item_id, lot_number)
);

-- 3. LOCATION HIERARCHY TABLE (Geographic stock isolation)
CREATE TABLE LocationHierarchy (
    location_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    location_name VARCHAR(100) NOT NULL, -- e.g., 'CT Suite 3', 'Central Rad Stockroom'
    facility_code VARCHAR(50) NOT NULL,
    parent_location_id UUID REFERENCES LocationHierarchy(location_id),
    is_active BOOLEAN DEFAULT TRUE
);

-- 4. STOCK LEDGER TABLE (Append-Only Transaction Ledger)
CREATE TYPE transaction_type_enum AS ENUM ('Inbound', 'Consume', 'Waste', 'Transfer', 'Adjustment');

CREATE TABLE StockLedger (
    transaction_id BIGSERIAL PRIMARY KEY,
    item_id UUID REFERENCES ItemMaster(item_id) ON DELETE RESTRICT,
    lot_id UUID REFERENCES LotDetail(lot_id) ON DELETE RESTRICT,
    location_id UUID REFERENCES LocationHierarchy(location_id) ON DELETE RESTRICT,
    delta_quantity INT NOT NULL, -- Negative for consumption, positive for restocking
    transaction_type transaction_type_enum NOT NULL,
    accession_number VARCHAR(50), -- Nullable, populates on 'Consume' via imaging procedure
    performed_by_user_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. REORDER PAR LEVELS TABLE
CREATE TABLE ReorderParLevels (
    par_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id UUID REFERENCES ItemMaster(item_id) ON DELETE CASCADE,
    location_id UUID REFERENCES LocationHierarchy(location_id) ON DELETE CASCADE,
    min_par_threshold INT NOT NULL,
    max_safety_stock INT NOT NULL,
    UNIQUE(item_id, location_id)
);
```

---

## 4. Functional Requirements

### 4.1 Automated Worklist Kit Mapping (FR-01)
* **Description:** The system shall link CPT (Current Procedural Terminology) codes to pre-defined "Default Consumption Kits".
* **Trigger:** When a study transitions to "In Progress" or "Completed" inside the RIS engine.
* **Execution:** System executes an internal trigger query lookup against the mapped procedure code and logs matching auto-deductions directly inside the `StockLedger` table.

### 4.2 Barcode Parsing Engine (FR-02)
* **Description:** Input text parsing fields across the technologist UI must natively interpret standard linear (Code 128) and matrix formats (GS1 DataMatrix).
* **Regex / Rules Processing:** The interface input field must extract the unique GTIN, Lot/Batch field, and Expiration strings directly out of complex raw GS1 barcodes, bypassing the need for multi-step configuration inputs.

### 4.3 Safe Batch and Expiration Safeguards (FR-03)
* **Description:** Technologists must receive a hard error warning UI dialog blocker if they attempt to scan or utilize an item whose extracted `expiration_date` from the `LotDetail` record is less than or equal to the current operational system date.
* **Recall Vector Audit:** System must provide a dedicated analytics layout lookup query capable of exposing every `accession_number` associated with a designated `lot_number` inside under 3 seconds in the event of a product recall alert.

---

## 5. Non-Functional & Operational Requirements

### 5.1 Concurrency & ACID Controls
* **Isolation Levels:** Every query operation updating ledger lines or computing aggregate availability must utilize standard transactional wraps using `SERIALIZABLE` or `READ COMMITTED` isolation levels to eliminate phantom read discrepancies during simultaneous checkout routines across discrete clinical suites.
* **Performance Benchmark:** Material inventory status query calculations must complete in less than 200ms during active user navigation, relying on aggregated views index tables.

### 5.2 Regulatory & Healthcare Compliance
* **Traceability:** In strict alignment with FDA UDI (Unique Device Identification) directives and standard global medical record handling rules, raw data strings pushed into the `StockLedger` must never be altered or hard deleted via administrative override interfaces.
* **Auditing:** Corrective adjustments must write an inverted countervailing transaction record preserving full historical visibility.

---

## 6. Integration Messaging Formats

### 6.1 Outbound Billing Payload (HL7 DFT^P03 Example)
When stock is checked out following a diagnostic study cycle, the system fires this payload string out to the central clinical financial router to bill the correct insurance codes:

```hl7
MSH|^~\&|RIS_INVENTORY|RAD_DEPT|EHR_BILLING|HOSP_FINANCE|202608190911||DFT^P03|MSG20260819_001|P|2.3
EVN|P03|202608190911
PID|1||PID1234567^^^MRN||DOE^JOHN||19800101|M
PV1|1|O|RAD^ROOM_CT3^01||||||||||||||||VISIT9876543
FT1|1|||202608190911||CG|74177|CT ABDOMEN & PELVIS WITH CONTRAST||1|150.00|||||RAD^ROOM_CT3|00123456^OMNIPAQUE_100ML^LOT_B9921
```

### 6.2 Modern Procurement Integration Example (FHIR SupplyDelivery Engine)
For hospitals running modern health-tech integrations, the module exposes structural transaction payloads matching the standard FHIR `SupplyDelivery` pattern:

```json
{
  "resourceType": "SupplyDelivery",
  "id": "delivery-rad-ct3-0056",
  "status": "completed",
  "patient": {
    "reference": "Patient/1234567"
  },
  "type": {
    "coding": [
      {
        "system": "http://hl7.org/fhir/supply-item-type",
        "code": "medicinal-product",
        "display": "Contrast Media"
      }
    ]
  },
  "suppliedItem": {
    "quantity": {
      "value": 1,
      "unit": "vial"
    },
    "itemCodeableConcept": {
      "coding": [
        {
          "system": "http://hl7.org/fhir/sid/ndc",
          "code": "50242-064-10",
          "display": "Omnipaque 300 mgI/mL 100 mL"
        }
      ]
    }
  },
  "occurrenceDateTime": "2026-08-19T09:11:00Z"
}
```
