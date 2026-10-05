from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

SNOMED = "http://snomed.info/sct"
ICD10 = ("http://hl7.org/fhir/sid/icd-10-cm", "http://hl7.org/fhir/sid/icd-10")
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
LOINC = "http://loinc.org"
NPI = "http://hl7.org/fhir/sid/us-npi"

CONDITION_STATUS = {"active": "active", "recurrence": "active", "relapse": "active", "resolved": "resolved", "remission": "resolved", "inactive": "inactive"}
ALLERGY_STATUS = {"active": "active", "inactive": "inactive", "resolved": "resolved"}
MEDICATION_STATUS = {"active": "active", "stopped": "stopped", "cancelled": "stopped", "entered-in-error": "stopped", "completed": "completed"}
INTERPRETATION = {"L": "low", "LL": "low", "N": "normal", "H": "high", "HH": "high"}
ENCOUNTER_CLASS = {"AMB": "ambulatory", "VR": "virtual", "EMER": "emergency", "IMP": "inpatient", "ACUTE": "inpatient"}
OBSERVATION_CATEGORIES = ("laboratory", "vital-signs")
PLAN_STATUS = {"draft": "draft", "active": "active", "on-hold": "active", "completed": "completed", "revoked": "revoked", "entered-in-error": "revoked"}
GOAL_STATUS = {
    "proposed": "proposed",
    "planned": "proposed",
    "accepted": "active",
    "active": "active",
    "on-hold": "active",
    "completed": "achieved",
    "cancelled": "cancelled",
    "rejected": "cancelled",
    "entered-in-error": "cancelled",
}
ACTIVITY_STATUS = {
    "not-started": "not_started",
    "scheduled": "scheduled",
    "in-progress": "in_progress",
    "on-hold": "in_progress",
    "completed": "completed",
    "cancelled": "cancelled",
    "stopped": "cancelled",
    "entered-in-error": "cancelled",
}
ACTIVITY_KIND = {
    "Appointment": "appointment",
    "MedicationRequest": "medication",
    "CommunicationRequest": "education",
    "NutritionOrder": "education",
}


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _str(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first(value) -> dict:
    items = _list(value)
    return _dict(items[0]) if items else {}


def number(value) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            return None
    return None


def whole(value) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def date_part(value) -> date | None:
    text = _str(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def when(value) -> datetime | None:
    text = _str(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def coding(concept, prefer: tuple[str, ...] = ()) -> dict:
    concept = _dict(concept)
    codings = [item for item in _list(concept.get("coding")) if isinstance(item, dict)]
    chosen = next((item for system in prefer for item in codings if item.get("system") == system), None)
    if chosen is None and codings:
        chosen = codings[0]
    chosen = chosen or {}
    return {
        "code_system": _str(chosen.get("system")),
        "code": _str(chosen.get("code")),
        "display": _str(chosen.get("display")) or _str(concept.get("text")),
    }


def condition(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "Condition":
        return None
    raw_status = coding(resource.get("clinicalStatus"))["code"]
    return {
        **coding(resource.get("code"), (SNOMED, *ICD10)),
        "clinical_status": CONDITION_STATUS.get(raw_status or "", "active"),
        "onset_date": date_part(resource.get("onsetDateTime")) or date_part(_dict(resource.get("onsetPeriod")).get("start")),
        "abatement_date": date_part(resource.get("abatementDateTime")) or date_part(_dict(resource.get("abatementPeriod")).get("end")),
        "recorded_date": date_part(resource.get("recordedDate")),
    }


def allergy(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "AllergyIntolerance":
        return None
    criticality = _str(resource.get("criticality"))
    manifestation = _first(_first(resource.get("reaction")).get("manifestation"))
    raw_status = coding(resource.get("clinicalStatus"))["code"]
    return {
        **coding(resource.get("code"), (RXNORM, SNOMED)),
        "criticality": criticality if criticality in ("low", "high") else None,
        "reaction": coding(manifestation)["display"],
        "clinical_status": ALLERGY_STATUS.get(raw_status or "", "active"),
        "recorded_date": date_part(resource.get("recordedDate")),
    }


def medication_code(resource: dict) -> dict:
    concept = resource.get("medicationCodeableConcept")
    reference = _dict(resource.get("medicationReference"))
    target = _str(reference.get("reference"))
    if not concept and target and target.startswith("#"):
        for item in _list(resource.get("contained")):
            if _dict(item).get("resourceType") == "Medication" and item.get("id") == target[1:]:
                concept = item.get("code")
                break
    found = coding(concept, (RXNORM,))
    if found["display"] is None:
        found["display"] = _str(reference.get("display"))
    return found


def medication(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") not in ("MedicationRequest", "MedicationStatement"):
        return None
    code = medication_code(resource)
    if code["code"] is None and code["display"] is None:
        return None
    dosage = _first(resource.get("dosageInstruction")) or _first(resource.get("dosage"))
    period = _dict(resource.get("effectivePeriod"))
    dispense = _dict(resource.get("dispenseRequest"))
    return {
        **code,
        "status": MEDICATION_STATUS.get(_str(resource.get("status")) or "", "active"),
        "dose_text": _str(dosage.get("text")),
        "start_date": date_part(resource.get("authoredOn")) or date_part(period.get("start")) or date_part(resource.get("effectiveDateTime")),
        "end_date": date_part(period.get("end")),
        "prescriber": _str(_dict(resource.get("requester")).get("display")),
        "quantity": number(_dict(dispense.get("quantity")).get("value")),
        "refills_allowed": whole(dispense.get("numberOfRepeatsAllowed")),
        "days_supply": whole(_dict(dispense.get("expectedSupplyDuration")).get("value")),
    }


def medication_fill(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "MedicationDispense":
        return None
    code = medication_code(resource)
    dispensed_at = when(resource.get("whenHandedOver")) or when(resource.get("whenPrepared"))
    days_supply = whole(_dict(resource.get("daysSupply")).get("value"))
    expected = (dispensed_at + timedelta(days=days_supply)).date() if dispensed_at and days_supply else None
    return {
        **code,
        "dispensed_at": dispensed_at,
        "quantity": number(_dict(resource.get("quantity")).get("value")),
        "days_supply": days_supply,
        "pharmacy": _str(_dict(_first(resource.get("performer")).get("actor")).get("display")),
        "expected_refill_date": expected,
    }


def observation_category(resource: dict) -> str | None:
    for category in _list(resource.get("category")):
        for item in _list(_dict(category).get("coding")):
            if _dict(item).get("code") in OBSERVATION_CATEGORIES:
                return item["code"]
    return None


def _value(item: dict) -> dict:
    quantity = _dict(item.get("valueQuantity"))
    concept = item.get("valueCodeableConcept")
    reference = _first(item.get("referenceRange"))
    return {
        "value_number": number(quantity.get("value")),
        "value_text": _str(item.get("valueString")) or (coding(concept)["display"] if concept else None),
        "unit": _str(quantity.get("unit")) or _str(quantity.get("code")),
        "range_low": number(_dict(reference.get("low")).get("value")),
        "range_high": number(_dict(reference.get("high")).get("value")),
    }


def observations(resource: dict) -> list[dict]:
    if _dict(resource).get("resourceType") != "Observation":
        return []
    category = observation_category(resource)
    if category is None:
        return []
    effective_at = (
        when(resource.get("effectiveDateTime")) or when(_dict(resource.get("effectivePeriod")).get("start")) or when(resource.get("issued"))
    )
    components = [item for item in _list(resource.get("component")) if isinstance(item, dict)]
    rows = []
    for item in components or [resource]:
        value = _value(item)
        if value["value_number"] is None and value["value_text"] is None:
            continue
        rows.append(
            {
                **coding(item.get("code"), (LOINC,)),
                "category": category,
                **value,
                "interpretation": INTERPRETATION.get(coding(_first(item.get("interpretation")))["code"] or ""),
                "effective_at": effective_at,
            }
        )
    return rows


def lab_report(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "DiagnosticReport":
        return None
    references = (_dict(item).get("reference") for item in _list(resource.get("result")))
    return {
        **coding(resource.get("code"), (LOINC,)),
        "status": _str(resource.get("status")),
        "issued_at": when(resource.get("issued")) or when(resource.get("effectiveDateTime")),
        "performer": _str(_first(resource.get("performer")).get("display")),
        "result_ids": [reference.split("/")[-1] for reference in references if isinstance(reference, str) and "/" in reference],
    }


def encounter(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "Encounter":
        return None
    period = _dict(resource.get("period"))
    start_at = when(period.get("start"))
    if start_at is None:
        return None
    kind = _first(resource.get("type"))
    reason = _first(resource.get("reasonCode"))
    code = coding(kind)
    return {
        **code,
        "encounter_class": ENCOUNTER_CLASS.get((_str(_dict(resource.get("class")).get("code")) or "").upper(), "ambulatory"),
        "type": _str(kind.get("text")) or code["display"],
        "start_at": start_at,
        "end_at": when(period.get("end")),
        "practitioner": _str(_dict(_first(resource.get("participant")).get("individual")).get("display")),
        "organization": _str(_dict(resource.get("serviceProvider")).get("display")),
        "reason": _str(reason.get("text")) or coding(reason)["display"],
    }


def human_name(name: dict) -> str | None:
    text = _str(name.get("text"))
    if text:
        return text
    parts = [*_list(name.get("prefix")), *_list(name.get("given")), name.get("family")]
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip()) or None


def practitioner(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "Practitioner":
        return None
    name = human_name(_first(resource.get("name")))
    if name is None:
        return None
    npi = next((_str(_dict(item).get("value")) for item in _list(resource.get("identifier")) if _dict(item).get("system") == NPI), None)
    phone = next((_str(_dict(item).get("value")) for item in _list(resource.get("telecom")) if _dict(item).get("system") == "phone"), None)
    return {
        "code_system": NPI if npi else None,
        "code": npi,
        "display": name,
        "name": name,
        "role": None,
        "organization": None,
        "npi": npi,
        "phone": phone,
    }


def care_team(resource: dict) -> list[dict]:
    if _dict(resource).get("resourceType") != "CareTeam":
        return []
    organization = _str(_first(resource.get("managingOrganization")).get("display"))
    rows = []
    for participant in _list(resource.get("participant")):
        member = _dict(_dict(participant).get("member"))
        name = _str(member.get("display"))
        reference = _str(member.get("reference")) or ""
        if name is None or reference.startswith(("Organization/", "CareTeam/")):
            continue
        role = _first(participant.get("role"))
        rows.append(
            {
                "code_system": None,
                "code": None,
                "display": name,
                "name": name,
                "role": _str(role.get("text")) or coding(role)["display"],
                "organization": organization,
                "npi": None,
                "phone": None,
            }
        )
    return rows


def patient_mismatch(resource: dict, first_name: str | None, date_of_birth: date | None) -> str | None:
    if _dict(resource).get("resourceType") != "Patient":
        return None
    reasons = []
    born = date_part(resource.get("birthDate"))
    if born and date_of_birth and born != date_of_birth:
        reasons.append(f"birth date {born} is not {date_of_birth}")
    givens = {given.strip().lower() for name in _list(resource.get("name")) for given in _list(_dict(name).get("given")) if isinstance(given, str)}
    if givens and first_name and first_name.strip().lower() not in givens:
        reasons.append(f"given name {', '.join(sorted(givens))} is not {first_name}")
    return "; ".join(reasons) or None


def concept_text(concept) -> str | None:
    return _str(_dict(concept).get("text")) or coding(concept)["display"]


def patient(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "Patient":
        return None
    names = [_dict(name) for name in _list(resource.get("name"))]
    official = next((name for name in names if name.get("use") == "official"), names[0] if names else {})
    usual = next((name for name in names if name.get("use") == "usual"), {})
    address = _first(resource.get("address"))
    place = [part for part in (_str(address.get("city")), _str(address.get("state"))) if part]
    phone = next((_str(_dict(item).get("value")) for item in _list(resource.get("telecom")) if _dict(item).get("system") == "phone"), None)
    return {
        "first_name": _str(next(iter(_list(official.get("given"))), None)),
        "last_name": _str(official.get("family")),
        "preferred_name": _str(next(iter(_list(usual.get("given"))), None)),
        "date_of_birth": date_part(resource.get("birthDate")),
        "gender": _str(resource.get("gender")),
        "location": ", ".join(place) or None,
        "phone": phone,
    }


def immunization(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "Immunization":
        return None
    return {
        "display": concept_text(resource.get("vaccineCode")),
        "occurred_at": when(resource.get("occurrenceDateTime")),
        "status": _str(resource.get("status")),
    }


def procedure(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "Procedure":
        return None
    return {
        "display": concept_text(resource.get("code")),
        "performed_at": when(resource.get("performedDateTime")) or when(_dict(resource.get("performedPeriod")).get("start")),
        "status": _str(resource.get("status")),
    }


def document(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "DocumentReference":
        return None
    kind = concept_text(resource.get("type"))
    attachment = _dict(_first(resource.get("content")).get("attachment"))
    return {
        "title": _str(resource.get("description")) or kind,
        "date": when(resource.get("date")),
        "type": kind,
        "content_type": _str(attachment.get("contentType")),
        "has_attachment": bool(attachment.get("data") or attachment.get("url")),
    }


def plan_activity(item: dict) -> dict | None:
    detail = _dict(item.get("detail"))
    reference = _dict(item.get("reference"))
    description = concept_text(detail.get("code")) or concept_text(detail.get("productCodeableConcept")) or _str(detail.get("description"))
    description = description or _str(reference.get("display"))
    if description is None:
        return None
    kind = _str(detail.get("kind")) or (_str(reference.get("reference")) or "").split("/")[0]
    if detail.get("productCodeableConcept") or detail.get("productReference"):
        kind = "MedicationRequest"
    code = coding(detail.get("code"), (LOINC,))
    scheduled = _dict(detail.get("scheduledPeriod")).get("start") or detail.get("scheduledString")
    scheduled = scheduled or next(iter(_list(_dict(detail.get("scheduledTiming")).get("event"))), None)
    return {
        "kind": ACTIVITY_KIND.get(kind) or ("lab" if code["code_system"] == LOINC else "other"),
        "description": description,
        "status": ACTIVITY_STATUS.get(_str(detail.get("status")) or "", "not_started"),
        "scheduled_for": date_part(scheduled),
    }


def care_plan(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "CarePlan":
        return None
    activities = [found for item in _list(resource.get("activity")) if (found := plan_activity(_dict(item)))]
    # The first category is often only the US Core "assess-plan" code, which has no words.
    category = next((text for item in _list(resource.get("category")) if (text := concept_text(item))), None)
    references = (_dict(item).get("reference") for item in _list(resource.get("goal")))
    period = _dict(resource.get("period"))
    return {
        "title": (_str(resource.get("title")) or category or (activities[0]["description"] if activities else None) or "Care plan")[:300],
        "description": _str(resource.get("description")),
        "status": PLAN_STATUS.get(_str(resource.get("status")) or "", "active"),
        "period_start": date_part(period.get("start")),
        "period_end": date_part(period.get("end")),
        "author": _str(_dict(resource.get("author")).get("display")),
        "activities": activities,
        "goal_ids": [reference.split("/")[-1] for reference in references if isinstance(reference, str) and "/" in reference],
    }


def goal(resource: dict) -> dict | None:
    if _dict(resource).get("resourceType") != "Goal":
        return None
    description = concept_text(resource.get("description"))
    if description is None:
        return None
    target = _first(resource.get("target"))
    quantity = _dict(target.get("detailQuantity")) or _dict(_dict(target.get("detailRange")).get("high"))
    measure = coding(target.get("measure"), (LOINC,))
    status = GOAL_STATUS.get(_str(resource.get("lifecycleStatus")) or "", "active")
    if coding(resource.get("achievementStatus"))["code"] == "achieved":
        status = "achieved"
    return {
        "description": description,
        "target_code": measure["code"],
        "target_value": number(quantity.get("value")),
        "target_unit": _str(quantity.get("unit")) or _str(quantity.get("code")),
        "due_date": date_part(target.get("dueDate")),
        "status": status,
    }
