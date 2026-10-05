import json
from datetime import date, datetime, timezone
from decimal import Decimal

from app import fhir_map

UTC = timezone.utc
SNOMED = "http://snomed.info/sct"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
LOINC = "http://loinc.org"
TERM = "http://terminology.hl7.org/CodeSystem"
PATIENT_REF = {"reference": "Patient/pat-1"}


def meta(version="1", updated="2026-09-20T12:00:00Z") -> dict:
    return {"versionId": version, "lastUpdated": updated}


PATIENT = {
    "resourceType": "Patient",
    "id": "pat-1",
    "meta": meta(),
    "name": [{"family": "Ruiz", "given": ["Elena"]}],
    "birthDate": "1971-03-14",
    "gender": "female",
}
CONDITION = {
    "resourceType": "Condition",
    "id": "cond-1",
    "meta": meta("3"),
    "clinicalStatus": {"coding": [{"system": f"{TERM}/condition-clinical", "code": "active"}]},
    "verificationStatus": {"coding": [{"system": f"{TERM}/condition-ver-status", "code": "confirmed"}]},
    "category": [{"coding": [{"system": f"{TERM}/condition-category", "code": "problem-list-item"}]}],
    "code": {
        "coding": [
            {"system": ICD10, "code": "E11.9", "display": "Type 2 diabetes mellitus without complications"},
            {"system": SNOMED, "code": "44054006", "display": "Type 2 diabetes mellitus"},
        ],
        "text": "Type 2 diabetes",
    },
    "subject": PATIENT_REF,
    "onsetDateTime": "2021-04-02",
    "recordedDate": "2021-04-02T10:15:00Z",
}
RESOLVED_CONDITION = {
    "resourceType": "Condition",
    "id": "cond-2",
    "meta": meta("1", "2026-09-19T08:00:00Z"),
    "clinicalStatus": {"coding": [{"system": f"{TERM}/condition-clinical", "code": "resolved"}]},
    "code": {"coding": [{"system": SNOMED, "code": "195967001", "display": "Asthma"}]},
    "subject": PATIENT_REF,
    "onsetPeriod": {"start": "2010-05-01"},
    "abatementDateTime": "2018-06-30T00:00:00Z",
}
ALLERGY = {
    "resourceType": "AllergyIntolerance",
    "id": "all-1",
    "meta": meta(),
    "clinicalStatus": {"coding": [{"system": f"{TERM}/allergyintolerance-clinical", "code": "active"}]},
    "type": "allergy",
    "category": ["medication"],
    "criticality": "high",
    "code": {"coding": [{"system": RXNORM, "code": "7980", "display": "Penicillin"}]},
    "patient": PATIENT_REF,
    "recordedDate": "2015-02-11",
    "reaction": [{"manifestation": [{"coding": [{"system": SNOMED, "code": "247472004", "display": "Hives"}]}], "severity": "moderate"}],
}
MEDICATION_REQUEST = {
    "resourceType": "MedicationRequest",
    "id": "rx-1",
    "meta": meta("2"),
    "status": "active",
    "intent": "order",
    "medicationCodeableConcept": {
        "coding": [{"system": RXNORM, "code": "861007", "display": "Metformin 500 MG Oral Tablet"}],
        "text": "Metformin 500 mg tablet",
    },
    "subject": PATIENT_REF,
    "authoredOn": "2021-04-10T09:00:00Z",
    "requester": {"reference": "Practitioner/dr-1", "display": "Dr. A. Patel"},
    "dosageInstruction": [{"text": "Take 1 tablet twice a day with meals"}],
    "dispenseRequest": {
        "numberOfRepeatsAllowed": 3,
        "quantity": {"value": 60, "unit": "tablet"},
        "expectedSupplyDuration": {"value": 30, "unit": "days"},
    },
}
MEDICATION_STATEMENT = {
    "resourceType": "MedicationStatement",
    "id": "ms-1",
    "meta": meta(),
    "status": "active",
    "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": "861007", "display": "Metformin 500 MG Oral Tablet"}]},
    "subject": PATIENT_REF,
    "effectivePeriod": {"start": "2021-04-10"},
    "dosage": [{"text": "1 tablet twice daily"}],
}
STOPPED_STATEMENT = {
    "resourceType": "MedicationStatement",
    "id": "ms-2",
    "meta": meta(),
    "status": "stopped",
    "contained": [
        {
            "resourceType": "Medication",
            "id": "med-2",
            "code": {"coding": [{"system": RXNORM, "code": "197361", "display": "Amlodipine 5 MG Oral Tablet"}]},
        }
    ],
    "medicationReference": {"reference": "#med-2"},
    "subject": PATIENT_REF,
    "effectivePeriod": {"start": "2019-01-05", "end": "2024-02-01"},
}
DISPENSE = {
    "resourceType": "MedicationDispense",
    "id": "disp-1",
    "meta": meta(),
    "status": "completed",
    "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": "861007", "display": "Metformin 500 MG Oral Tablet"}]},
    "subject": PATIENT_REF,
    "performer": [{"actor": {"display": "Example Pharmacy"}}],
    "quantity": {"value": 60, "unit": "tablet"},
    "daysSupply": {"value": 30, "unit": "days"},
    "whenPrepared": "2026-09-04T13:00:00Z",
    "whenHandedOver": "2026-09-04T14:10:00Z",
}
OLDER_DISPENSE = {**DISPENSE, "id": "disp-0", "whenPrepared": "2026-08-05T14:00:00Z", "whenHandedOver": "2026-08-05T15:00:00Z"}
ORPHAN_DISPENSE = {
    **DISPENSE,
    "id": "disp-x",
    "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": "999999", "display": "Something else"}]},
}
A1C_MARCH = {
    "resourceType": "Observation",
    "id": "obs-a1c-1",
    "meta": meta(),
    "status": "final",
    "category": [{"coding": [{"system": f"{TERM}/observation-category", "code": "laboratory", "display": "Laboratory"}]}],
    "code": {"coding": [{"system": LOINC, "code": "4548-4", "display": "Hemoglobin A1c"}], "text": "HbA1c"},
    "subject": PATIENT_REF,
    "effectiveDateTime": "2026-03-10T08:30:00Z",
    "issued": "2026-03-11T10:00:00Z",
    "valueQuantity": {"value": 7.4, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"},
    "interpretation": [{"coding": [{"system": f"{TERM}/v3-ObservationInterpretation", "code": "H", "display": "High"}]}],
    "referenceRange": [{"low": {"value": 4.0, "unit": "%"}, "high": {"value": 5.6, "unit": "%"}}],
}
A1C_SEPTEMBER = {
    **A1C_MARCH,
    "id": "obs-a1c-2",
    "effectiveDateTime": "2026-09-16T08:30:00Z",
    "issued": "2026-09-17T09:00:00Z",
    "valueQuantity": {"value": 7.1, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"},
}
BLOOD_PRESSURE = {
    "resourceType": "Observation",
    "id": "obs-bp-1",
    "meta": meta(),
    "status": "final",
    "category": [{"coding": [{"system": f"{TERM}/observation-category", "code": "vital-signs"}]}],
    "code": {"coding": [{"system": LOINC, "code": "85354-9", "display": "Blood pressure panel"}]},
    "subject": PATIENT_REF,
    "effectiveDateTime": "2026-09-16T14:05:00Z",
    "component": [
        {
            "code": {"coding": [{"system": LOINC, "code": "8480-6", "display": "Systolic blood pressure"}]},
            "valueQuantity": {"value": 138, "unit": "mmHg"},
            "interpretation": [{"coding": [{"code": "H"}]}],
        },
        {
            "code": {"coding": [{"system": LOINC, "code": "8462-4", "display": "Diastolic blood pressure"}]},
            "valueQuantity": {"value": 84, "unit": "mmHg"},
            "interpretation": [{"coding": [{"code": "N"}]}],
        },
    ],
}
URINE = {
    "resourceType": "Observation",
    "id": "obs-urine-1",
    "meta": meta(),
    "status": "final",
    "category": [{"coding": [{"system": f"{TERM}/observation-category", "code": "laboratory"}]}],
    "code": {"coding": [{"system": LOINC, "code": "20453-7", "display": "Erythrocytes [Presence] in Urine"}]},
    "subject": PATIENT_REF,
    "effectivePeriod": {"start": "2026-09-16T08:40:00Z"},
    "valueString": "Negative",
}
SURVEY = {
    "resourceType": "Observation",
    "id": "obs-survey-1",
    "meta": meta(),
    "status": "final",
    "category": [{"coding": [{"system": f"{TERM}/observation-category", "code": "survey"}]}],
    "code": {"coding": [{"system": LOINC, "code": "44261-6", "display": "PHQ-9 total score"}]},
    "subject": PATIENT_REF,
    "effectiveDateTime": "2026-09-16T14:00:00Z",
    "valueQuantity": {"value": 4},
}
REPORT = {
    "resourceType": "DiagnosticReport",
    "id": "rep-1",
    "meta": meta(),
    "status": "final",
    "category": [{"coding": [{"system": f"{TERM}/v2-0074", "code": "LAB"}]}],
    "code": {"coding": [{"system": LOINC, "code": "4548-4", "display": "Hemoglobin A1c"}]},
    "subject": PATIENT_REF,
    "effectiveDateTime": "2026-09-16T08:30:00Z",
    "issued": "2026-09-17T09:00:00Z",
    "performer": [{"display": "Example Lab"}],
    "result": [{"reference": "Observation/obs-a1c-2"}],
}
ENCOUNTER = {
    "resourceType": "Encounter",
    "id": "enc-1",
    "meta": meta(),
    "status": "finished",
    "class": {"system": f"{TERM}/v3-ActCode", "code": "AMB", "display": "ambulatory"},
    "type": [{"coding": [{"system": "http://www.ama-assn.org/go/cpt", "code": "99214", "display": "Office visit, established patient"}], "text": "Office visit"}],
    "subject": PATIENT_REF,
    "participant": [{"individual": {"reference": "Practitioner/dr-1", "display": "Dr. A. Patel"}}],
    "period": {"start": "2026-09-16T14:00:00Z", "end": "2026-09-16T14:30:00Z"},
    "reasonCode": [{"text": "Diabetes follow-up"}],
    "serviceProvider": {"reference": "Organization/org-1", "display": "Example Health"},
}
OLDER_ENCOUNTER = {
    **ENCOUNTER,
    "id": "enc-0",
    "class": {"system": f"{TERM}/v3-ActCode", "code": "VR", "display": "virtual"},
    "period": {"start": "2026-03-10T09:00:00Z", "end": "2026-03-10T09:20:00Z"},
    "reasonCode": [{"coding": [{"system": SNOMED, "code": "866149003", "display": "Annual review"}]}],
}
PRACTITIONER = {
    "resourceType": "Practitioner",
    "id": "dr-1",
    "meta": meta(),
    "identifier": [{"system": "http://hl7.org/fhir/sid/us-npi", "value": "1234567890"}],
    "name": [{"family": "Patel", "given": ["Anita"], "prefix": ["Dr."]}],
    "telecom": [{"system": "phone", "value": "+1 555 010 0000", "use": "work"}, {"system": "email", "value": "patel@example.com"}],
}
CARE_TEAM = {
    "resourceType": "CareTeam",
    "id": "ct-1",
    "meta": meta(),
    "status": "active",
    "subject": PATIENT_REF,
    "managingOrganization": [{"display": "Example Health"}],
    "participant": [
        {"role": [{"text": "Primary care"}], "member": {"reference": "Practitioner/dr-1", "display": "Dr. Anita Patel"}},
        {"role": [{"coding": [{"display": "Diabetes educator"}]}], "member": {"reference": "Practitioner/nurse-1", "display": "Sam Lee, RN"}},
        {"member": {"reference": "Organization/org-1", "display": "Example Health"}},
    ],
}
IMMUNIZATION = {
    "resourceType": "Immunization",
    "id": "imm-1",
    "meta": meta(),
    "status": "completed",
    "vaccineCode": {"coding": [{"system": "http://hl7.org/fhir/sid/cvx", "code": "140", "display": "Influenza, seasonal"}]},
    "patient": PATIENT_REF,
    "occurrenceDateTime": "2025-10-02",
}
PROCEDURE = {
    "resourceType": "Procedure",
    "id": "proc-1",
    "meta": meta(),
    "status": "completed",
    "code": {"coding": [{"system": SNOMED, "code": "73761001", "display": "Colonoscopy"}]},
    "subject": PATIENT_REF,
    "performedPeriod": {"start": "2024-06-11T09:00:00Z", "end": "2024-06-11T10:00:00Z"},
}
DOCUMENT = {
    "resourceType": "DocumentReference",
    "id": "doc-1",
    "meta": meta(),
    "status": "current",
    "type": {"coding": [{"system": LOINC, "code": "11506-3", "display": "Progress note"}]},
    "description": "Visit summary",
    "date": "2026-09-12T15:30:00Z",
    "subject": PATIENT_REF,
    "content": [{"attachment": {"contentType": "application/pdf", "data": "JVBERi0x"}}],
}
GOAL = {
    "resourceType": "Goal",
    "id": "goal-1",
    "meta": meta(),
    "lifecycleStatus": "active",
    "description": {"text": "Keep A1c below 7%"},
    "subject": PATIENT_REF,
    "target": [
        {
            "measure": {"coding": [{"system": LOINC, "code": "4548-4", "display": "Hemoglobin A1c"}]},
            "detailQuantity": {"value": 7, "unit": "%"},
            "dueDate": "2027-03-31",
        }
    ],
}
CARE_PLAN = {
    "resourceType": "CarePlan",
    "id": "cp-1",
    "meta": meta(),
    "status": "active",
    "intent": "plan",
    "category": [
        {"coding": [{"system": "http://hl7.org/fhir/us/core/CodeSystem/careplan-category", "code": "assess-plan"}]},
        {"coding": [{"system": SNOMED, "code": "698360004", "display": "Diabetes self management plan"}]},
    ],
    "description": "Keep A1c and blood pressure in range.",
    "subject": PATIENT_REF,
    "period": {"start": "2026-04-01T09:00:00-05:00"},
    "author": {"reference": "Practitioner/dr-1", "display": "Dr. A. Patel"},
    "goal": [{"reference": "Goal/goal-1"}, {"reference": "Goal/goal-missing"}],
    "activity": [
        {
            "detail": {
                "code": {"coding": [{"system": LOINC, "code": "4548-4", "display": "Hemoglobin A1c"}], "text": "A1c test every 3 months"},
                "status": "scheduled",
                "scheduledPeriod": {"start": "2026-12-15T08:00:00Z"},
            }
        },
        {"detail": {"kind": "CommunicationRequest", "code": {"text": "Diabetes nutrition class"}, "status": "not-started", "scheduledString": "next spring"}},
        {"detail": {"productCodeableConcept": {"coding": [{"system": RXNORM, "code": "860975", "display": "Metformin 500 MG"}]}, "status": "in-progress"}},
        {"reference": {"reference": "Appointment/appt-1", "display": "Follow-up visit"}},
        {"detail": {"status": "completed"}},
    ],
}
ALL = [
    PATIENT,
    CONDITION,
    RESOLVED_CONDITION,
    ALLERGY,
    MEDICATION_REQUEST,
    MEDICATION_STATEMENT,
    STOPPED_STATEMENT,
    DISPENSE,
    OLDER_DISPENSE,
    ORPHAN_DISPENSE,
    A1C_MARCH,
    A1C_SEPTEMBER,
    BLOOD_PRESSURE,
    URINE,
    SURVEY,
    REPORT,
    ENCOUNTER,
    OLDER_ENCOUNTER,
    PRACTITIONER,
    CARE_TEAM,
    IMMUNIZATION,
    PROCEDURE,
    DOCUMENT,
]


def ndjson(*resources) -> bytes:
    return "\n".join(json.dumps(resource) for resource in resources).encode() + b"\n"


def test_condition_prefers_snomed_and_maps_the_status():
    assert fhir_map.condition(CONDITION) == {
        "code_system": SNOMED,
        "code": "44054006",
        "display": "Type 2 diabetes mellitus",
        "clinical_status": "active",
        "onset_date": date(2021, 4, 2),
        "abatement_date": None,
        "recorded_date": date(2021, 4, 2),
    }
    resolved = fhir_map.condition(RESOLVED_CONDITION)
    assert (resolved["clinical_status"], resolved["onset_date"], resolved["abatement_date"]) == ("resolved", date(2010, 5, 1), date(2018, 6, 30))
    icd_only = {**CONDITION, "code": {"coding": [CONDITION["code"]["coding"][0]]}, "clinicalStatus": {"coding": [{"code": "remission"}]}}
    assert fhir_map.condition(icd_only)["code"] == "E11.9" and fhir_map.condition(icd_only)["clinical_status"] == "resolved"
    text_only = {**CONDITION, "code": {"text": "Back pain"}, "clinicalStatus": {"coding": [{"code": "inactive"}]}}
    assert fhir_map.condition(text_only)["display"] == "Back pain" and fhir_map.condition(text_only)["code"] is None
    assert fhir_map.condition(text_only)["clinical_status"] == "inactive"
    assert fhir_map.condition(ALLERGY) is None


def test_allergy_takes_the_first_reaction():
    assert fhir_map.allergy(ALLERGY) == {
        "code_system": RXNORM,
        "code": "7980",
        "display": "Penicillin",
        "criticality": "high",
        "reaction": "Hives",
        "clinical_status": "active",
        "recorded_date": date(2015, 2, 11),
    }
    unknown = {**ALLERGY, "criticality": "unable-to-assess", "reaction": [{"manifestation": [{"text": "Rash"}]}]}
    assert fhir_map.allergy(unknown)["criticality"] is None and fhir_map.allergy(unknown)["reaction"] == "Rash"
    assert fhir_map.allergy({**ALLERGY, "reaction": []})["reaction"] is None


def test_medication_request_and_statement():
    assert fhir_map.medication(MEDICATION_REQUEST) == {
        "code_system": RXNORM,
        "code": "861007",
        "display": "Metformin 500 MG Oral Tablet",
        "status": "active",
        "dose_text": "Take 1 tablet twice a day with meals",
        "start_date": date(2021, 4, 10),
        "end_date": None,
        "prescriber": "Dr. A. Patel",
        "quantity": Decimal("60"),
        "refills_allowed": 3,
        "days_supply": 30,
    }
    stopped = fhir_map.medication(STOPPED_STATEMENT)
    assert (stopped["code"], stopped["display"], stopped["status"]) == ("197361", "Amlodipine 5 MG Oral Tablet", "stopped")
    assert (stopped["start_date"], stopped["end_date"], stopped["dose_text"], stopped["prescriber"]) == (date(2019, 1, 5), date(2024, 2, 1), None, None)
    assert fhir_map.medication(MEDICATION_STATEMENT)["dose_text"] == "1 tablet twice daily"
    for raw, mapped in (("cancelled", "stopped"), ("entered-in-error", "stopped"), ("completed", "completed"), ("on-hold", "active"), (None, "active")):
        assert fhir_map.medication({**MEDICATION_REQUEST, "status": raw})["status"] == mapped
    by_reference = {**MEDICATION_REQUEST, "medicationCodeableConcept": None, "medicationReference": {"reference": "Medication/m9", "display": "Lisinopril"}}
    assert fhir_map.medication(by_reference)["display"] == "Lisinopril" and fhir_map.medication(by_reference)["code"] is None
    assert fhir_map.medication({**MEDICATION_REQUEST, "medicationCodeableConcept": None}) is None


def test_medication_fill_computes_the_expected_refill():
    assert fhir_map.medication_fill(DISPENSE) == {
        "code_system": RXNORM,
        "code": "861007",
        "display": "Metformin 500 MG Oral Tablet",
        "dispensed_at": datetime(2026, 9, 4, 14, 10, tzinfo=UTC),
        "quantity": Decimal("60"),
        "days_supply": 30,
        "pharmacy": "Example Pharmacy",
        "expected_refill_date": date(2026, 10, 4),
    }
    prepared_only = {**DISPENSE, "whenHandedOver": None, "daysSupply": None}
    assert fhir_map.medication_fill(prepared_only)["dispensed_at"] == datetime(2026, 9, 4, 13, 0, tzinfo=UTC)
    assert fhir_map.medication_fill(prepared_only)["expected_refill_date"] is None


def test_observations_cover_labs_vitals_with_components_and_text_values():
    (a1c,) = fhir_map.observations(A1C_MARCH)
    assert a1c == {
        "code_system": LOINC,
        "code": "4548-4",
        "display": "Hemoglobin A1c",
        "category": "laboratory",
        "value_number": Decimal("7.4"),
        "value_text": None,
        "unit": "%",
        "range_low": Decimal("4.0"),
        "range_high": Decimal("5.6"),
        "interpretation": "high",
        "effective_at": datetime(2026, 3, 10, 8, 30, tzinfo=UTC),
    }
    systolic, diastolic = fhir_map.observations(BLOOD_PRESSURE)
    assert (systolic["code"], systolic["value_number"], systolic["unit"], systolic["interpretation"]) == ("8480-6", Decimal("138"), "mmHg", "high")
    assert (diastolic["code"], diastolic["value_number"], diastolic["interpretation"]) == ("8462-4", Decimal("84"), "normal")
    assert systolic["category"] == "vital-signs" and systolic["effective_at"] == datetime(2026, 9, 16, 14, 5, tzinfo=UTC)
    (urine,) = fhir_map.observations(URINE)
    assert (urine["value_text"], urine["value_number"], urine["effective_at"]) == ("Negative", None, datetime(2026, 9, 16, 8, 40, tzinfo=UTC))
    assert fhir_map.observations(SURVEY) == []
    coded = {**URINE, "valueString": None, "valueCodeableConcept": {"coding": [{"display": "Positive"}]}, "effectivePeriod": None, "issued": "2026-09-17T00:00:00Z"}
    (row,) = fhir_map.observations(coded)
    assert row["value_text"] == "Positive" and row["effective_at"] == datetime(2026, 9, 17, tzinfo=UTC)
    assert fhir_map.observations({**URINE, "valueString": None}) == []
    low = {**A1C_MARCH, "interpretation": [{"coding": [{"code": "LL"}]}]}
    assert fhir_map.observations(low)[0]["interpretation"] == "low"
    assert fhir_map.observations({**A1C_MARCH, "interpretation": [{"coding": [{"code": "A"}]}]})[0]["interpretation"] is None


def test_lab_report_lists_its_results():
    assert fhir_map.lab_report(REPORT) == {
        "code_system": LOINC,
        "code": "4548-4",
        "display": "Hemoglobin A1c",
        "status": "final",
        "issued_at": datetime(2026, 9, 17, 9, 0, tzinfo=UTC),
        "performer": "Example Lab",
        "result_ids": ["obs-a1c-2"],
    }
    assert fhir_map.lab_report({**REPORT, "issued": None, "result": [{"reference": "#contained"}]})["issued_at"] == datetime(2026, 9, 16, 8, 30, tzinfo=UTC)
    assert fhir_map.lab_report({**REPORT, "result": [{"reference": "#contained"}]})["result_ids"] == []


def test_encounter_maps_the_class_and_the_fields():
    assert fhir_map.encounter(ENCOUNTER) == {
        "code_system": "http://www.ama-assn.org/go/cpt",
        "code": "99214",
        "display": "Office visit, established patient",
        "encounter_class": "ambulatory",
        "type": "Office visit",
        "start_at": datetime(2026, 9, 16, 14, 0, tzinfo=UTC),
        "end_at": datetime(2026, 9, 16, 14, 30, tzinfo=UTC),
        "practitioner": "Dr. A. Patel",
        "organization": "Example Health",
        "reason": "Diabetes follow-up",
    }
    older = fhir_map.encounter(OLDER_ENCOUNTER)
    assert (older["encounter_class"], older["reason"]) == ("virtual", "Annual review")
    for raw, mapped in (("EMER", "emergency"), ("IMP", "inpatient"), ("ACUTE", "inpatient"), ("HH", "ambulatory"), (None, "ambulatory")):
        assert fhir_map.encounter({**ENCOUNTER, "class": {"code": raw}})["encounter_class"] == mapped
    assert fhir_map.encounter({**ENCOUNTER, "period": {"end": "2026-09-16T14:30:00Z"}}) is None
    bare = fhir_map.encounter({**ENCOUNTER, "type": [], "participant": [], "reasonCode": [], "serviceProvider": None})
    assert (bare["type"], bare["practitioner"], bare["reason"], bare["organization"], bare["code"]) == (None,) * 5


def test_practitioner_and_care_team():
    assert fhir_map.practitioner(PRACTITIONER) == {
        "code_system": "http://hl7.org/fhir/sid/us-npi",
        "code": "1234567890",
        "display": "Dr. Anita Patel",
        "name": "Dr. Anita Patel",
        "role": None,
        "organization": None,
        "npi": "1234567890",
        "phone": "+1 555 010 0000",
    }
    assert fhir_map.practitioner({**PRACTITIONER, "name": [{"text": "A. Patel MD"}], "identifier": [], "telecom": []})["name"] == "A. Patel MD"
    assert fhir_map.practitioner({**PRACTITIONER, "name": []}) is None
    assert fhir_map.care_team(CARE_TEAM) == [
        {
            "code_system": None,
            "code": None,
            "display": "Dr. Anita Patel",
            "name": "Dr. Anita Patel",
            "role": "Primary care",
            "organization": "Example Health",
            "npi": None,
            "phone": None,
        },
        {
            "code_system": None,
            "code": None,
            "display": "Sam Lee, RN",
            "name": "Sam Lee, RN",
            "role": "Diabetes educator",
            "organization": "Example Health",
            "npi": None,
            "phone": None,
        },
    ]


def test_patient_mismatch_checks_name_and_birth_date():
    assert fhir_map.patient_mismatch(PATIENT, "Elena", date(1971, 3, 14)) is None
    assert fhir_map.patient_mismatch(PATIENT, "elena", None) is None
    assert fhir_map.patient_mismatch(PATIENT, None, None) is None
    assert fhir_map.patient_mismatch(PATIENT, "John", date(1980, 1, 1)) == "birth date 1971-03-14 is not 1980-01-01; given name elena is not John"
    assert fhir_map.patient_mismatch(CONDITION, "John", None) is None


def test_patient_uses_the_official_and_usual_names():
    assert fhir_map.patient(PATIENT) == {
        "first_name": "Elena",
        "last_name": "Ruiz",
        "preferred_name": None,
        "date_of_birth": date(1971, 3, 14),
        "gender": "female",
        "location": None,
        "phone": None,
    }
    full = {
        **PATIENT,
        "name": [{"use": "usual", "given": ["Lena"]}, {"use": "official", "family": "Ruiz", "given": ["Elena", "Maria"]}],
        "address": [{"line": ["1 Main St"], "city": "Arlington", "state": "VA"}, {"city": "Elsewhere"}],
        "telecom": [{"system": "email", "value": "elena@example.com"}, {"system": "phone", "value": "555-0100"}],
    }
    assert fhir_map.patient(full) | {"date_of_birth": None} == {
        "first_name": "Elena",
        "last_name": "Ruiz",
        "preferred_name": "Lena",
        "date_of_birth": None,
        "gender": "female",
        "location": "Arlington, VA",
        "phone": "555-0100",
    }
    assert fhir_map.patient({**PATIENT, "address": [{"state": "VA"}]})["location"] == "VA"


def test_immunization_procedure_and_document():
    assert fhir_map.immunization(IMMUNIZATION) == {"display": "Influenza, seasonal", "occurred_at": datetime(2025, 10, 2, tzinfo=UTC), "status": "completed"}
    assert fhir_map.immunization({**IMMUNIZATION, "vaccineCode": {"text": "Flu shot", "coding": []}})["display"] == "Flu shot"
    assert fhir_map.procedure(PROCEDURE) == {"display": "Colonoscopy", "performed_at": datetime(2024, 6, 11, 9, tzinfo=UTC), "status": "completed"}
    assert fhir_map.procedure({**PROCEDURE, "performedDateTime": "2024-07-01T08:00:00Z"})["performed_at"] == datetime(2024, 7, 1, 8, tzinfo=UTC)
    assert fhir_map.document(DOCUMENT) == {
        "title": "Visit summary",
        "date": datetime(2026, 9, 12, 15, 30, tzinfo=UTC),
        "type": "Progress note",
        "content_type": "application/pdf",
        "has_attachment": True,
    }
    bare = fhir_map.document({**DOCUMENT, "description": None, "content": []})
    assert (bare["title"], bare["content_type"], bare["has_attachment"]) == ("Progress note", None, False)


def test_malformed_resources_are_skipped_not_raised():
    junk = [
        {"resourceType": "Condition", "code": "nope", "clinicalStatus": [], "onsetDateTime": 42},
        {"resourceType": "AllergyIntolerance", "code": [], "reaction": "bad", "criticality": 3},
        {"resourceType": "MedicationRequest", "medicationCodeableConcept": {"coding": "x"}, "dispenseRequest": "no"},
        {"resourceType": "MedicationDispense", "medicationCodeableConcept": {"coding": [{"code": "1"}]}, "quantity": "x", "whenHandedOver": "soon"},
        {"resourceType": "Observation", "category": "laboratory", "code": None, "valueQuantity": {"value": "n/a"}},
        {"resourceType": "Observation", "category": [{"coding": [{"code": "laboratory"}]}], "component": [{"code": "x"}], "effectiveDateTime": "2026"},
        {"resourceType": "DiagnosticReport", "result": "Observation/1", "performer": "lab"},
        {"resourceType": "Encounter", "class": "AMB", "period": "yesterday", "participant": [{"individual": "x"}]},
        {"resourceType": "Practitioner", "name": "Dr. X", "identifier": "npi"},
        {"resourceType": "CareTeam", "participant": [{"member": "x"}, {"member": {"display": 1}}]},
        {"resourceType": "Patient", "name": "x", "birthDate": 1971},
        {"resourceType": "Patient", "name": [{"given": "Elena", "family": 3}], "address": "here", "telecom": [None]},
        {"resourceType": "Immunization", "vaccineCode": "flu", "occurrenceDateTime": 2025},
        {"resourceType": "Procedure", "code": [], "performedPeriod": "then"},
        {"resourceType": "DocumentReference", "type": None, "content": [{"attachment": "x"}]},
        "not even a dict",
        None,
    ]
    for resource in junk:
        for mapper in (
            fhir_map.condition,
            fhir_map.allergy,
            fhir_map.medication,
            fhir_map.medication_fill,
            fhir_map.lab_report,
            fhir_map.encounter,
            fhir_map.practitioner,
            fhir_map.patient,
            fhir_map.immunization,
            fhir_map.procedure,
            fhir_map.document,
            fhir_map.care_plan,
            fhir_map.goal,
        ):
            mapper(resource)
        fhir_map.observations(resource)
        fhir_map.care_team(resource)
        fhir_map.patient_mismatch(resource, "Elena", date(1971, 3, 14))
    assert fhir_map.condition(junk[0])["clinical_status"] == "active" and fhir_map.condition(junk[0])["onset_date"] is None
    assert fhir_map.medication(junk[2]) is None
    assert fhir_map.observations(junk[4]) == [] and fhir_map.observations(junk[5]) == []
    assert fhir_map.encounter(junk[7]) is None
    assert fhir_map.care_team(junk[9]) == []


def test_care_plan_and_goal():
    assert fhir_map.care_plan(CARE_PLAN) == {
        "title": "Diabetes self management plan",
        "description": "Keep A1c and blood pressure in range.",
        "status": "active",
        "period_start": date(2026, 4, 1),
        "period_end": None,
        "author": "Dr. A. Patel",
        "activities": [
            {"kind": "lab", "description": "A1c test every 3 months", "status": "scheduled", "scheduled_for": date(2026, 12, 15)},
            {"kind": "education", "description": "Diabetes nutrition class", "status": "not_started", "scheduled_for": None},
            {"kind": "medication", "description": "Metformin 500 MG", "status": "in_progress", "scheduled_for": None},
            {"kind": "appointment", "description": "Follow-up visit", "status": "not_started", "scheduled_for": None},
        ],
        "goal_ids": ["goal-1", "goal-missing"],
    }
    bare = {"resourceType": "CarePlan", "status": "on-hold", "category": [{"coding": [{"code": "assess-plan"}]}]}
    assert fhir_map.care_plan(bare)["title"] == "Care plan" and fhir_map.care_plan(bare)["status"] == "active"
    assert fhir_map.care_plan({**bare, "activity": CARE_PLAN["activity"][1:], "status": "entered-in-error"})["title"] == "Diabetes nutrition class"
    assert fhir_map.care_plan({**bare, "title": "My plan", "status": "revoked"})["status"] == "revoked"
    assert fhir_map.goal(GOAL) == {
        "description": "Keep A1c below 7%",
        "target_code": "4548-4",
        "target_value": Decimal("7"),
        "target_unit": "%",
        "due_date": date(2027, 3, 31),
        "status": "active",
    }
    achieved = {**GOAL, "lifecycleStatus": "completed", "target": [], "description": {"coding": [{"display": "Walk daily"}]}}
    assert fhir_map.goal(achieved) == {
        "description": "Walk daily",
        "target_code": None,
        "target_value": None,
        "target_unit": None,
        "due_date": None,
        "status": "achieved",
    }
    assert fhir_map.goal({**GOAL, "description": {}}) is None
    for junk in ({"resourceType": "CarePlan", "activity": ["x", {"detail": "y"}], "category": "c", "period": [], "goal": [None, {"reference": 3}]},
                 {"resourceType": "Goal", "description": "x", "target": "t"}):
        fhir_map.care_plan(junk)
        fhir_map.goal(junk)
