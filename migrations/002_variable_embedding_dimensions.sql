ALTER TABLE relationship_substrate.person
  ALTER COLUMN content_embedding TYPE vector;

ALTER TABLE relationship_substrate.organization
  ALTER COLUMN content_embedding TYPE vector;
