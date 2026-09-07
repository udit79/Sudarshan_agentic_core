export function toCaseDocument(body, ownerId) {
  return {
    caseId: body.case_id,
    ownerId,
    name: body.name,
    classificationLevel: body.classification_level,
    distribution: body.distribution,
  };
}
