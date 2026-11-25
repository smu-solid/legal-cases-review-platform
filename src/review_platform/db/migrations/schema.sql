CREATE SCHEMA IF NOT EXISTS review_platform;

CREATE FUNCTION review_platform.freeze_published_review_count() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF OLD.status IN ('published', 'closed') AND
             COALESCE((NEW.policy_json->>'minimum_reviews_per_case')::integer, 2)
             IS DISTINCT FROM
             COALESCE((OLD.policy_json->>'minimum_reviews_per_case')::integer, 2)
          THEN
            RAISE EXCEPTION 'number of reviews per case is frozen after publication';
          END IF;
          RETURN NEW;
        END;
        $$;

CREATE FUNCTION review_platform.guard_proposal_adjudication_item() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'proposal membership history is immutable';
          END IF;
          IF OLD.state != 'pending' OR
             ROW(NEW.id,NEW.tenant_id,NEW.campaign_id,NEW.case_id,NEW.group_id,NEW.adjudicator_id,
                 NEW.proposal_ids_json,NEW.extracted_adjudication_id,NEW.origin,NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id,OLD.tenant_id,OLD.campaign_id,OLD.case_id,OLD.group_id,OLD.adjudicator_id,
                 OLD.proposal_ids_json,OLD.extracted_adjudication_id,OLD.origin,OLD.created_at)
          THEN RAISE EXCEPTION 'submitted decisions and original membership are immutable'; END IF;
          RETURN NEW;
        END; $$;

CREATE FUNCTION review_platform.guard_reviewer_proposal() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                
        IF OLD.state = 'submitted' OR OLD.submitted_at IS NOT NULL THEN
            RAISE EXCEPTION 'submitted reviewer proposals are immutable';
        END IF;
        RETURN OLD;
    
            END IF;
            IF OLD.state IN ('submitted', 'removed') OR
               NEW.id != OLD.id OR NEW.tenant_id != OLD.tenant_id OR
               NEW.assignment_id != OLD.assignment_id OR NEW.created_at != OLD.created_at OR
               NEW.campaign_id != OLD.campaign_id OR NEW.case_id != OLD.case_id OR
               NEW.reviewer_id != OLD.reviewer_id OR NEW.group_id != OLD.group_id OR
               NEW.original_value != OLD.original_value OR NEW.value_schema != OLD.value_schema
            THEN RAISE EXCEPTION 'reviewer proposal identity or submitted content is immutable';
            END IF;
            RETURN NEW;
        END; $$;

CREATE FUNCTION review_platform.protect_campaign_allocation_state() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'campaign rows are not deleted; close or supersede instead';
  END IF;
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
     OR NEW.key IS DISTINCT FROM OLD.key
     OR NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'campaign identity fields are immutable';
  END IF;
  IF OLD.status IN ('published', 'closed') AND (
     NEW.subject_kind IS DISTINCT FROM OLD.subject_kind
     OR NEW.review_kind IS DISTINCT FROM OLD.review_kind
     OR NEW.source_snapshot_id IS DISTINCT FROM OLD.source_snapshot_id
     OR NEW.allocation_policy_version IS DISTINCT FROM OLD.allocation_policy_version
     OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
     OR NEW.manifest_digest IS DISTINCT FROM OLD.manifest_digest
     OR NEW.published_at IS DISTINCT FROM OLD.published_at
  ) THEN
    RAISE EXCEPTION 'published campaign inputs are immutable';
  END IF;
  IF OLD.status = 'published' AND (
     (NEW.policy_json - ARRAY[
       'selected_reviewer_ids',
       'minimum_reviews_per_case',
       'case_filter',
       'case_id_selection',
       'case_selection_applies_to_topups',
       'case_id_selection_file_name'
     ]::text[]) IS DISTINCT FROM
     (OLD.policy_json - ARRAY[
       'selected_reviewer_ids',
       'minimum_reviews_per_case',
       'case_filter',
       'case_id_selection',
       'case_selection_applies_to_topups',
       'case_id_selection_file_name'
     ]::text[])
  ) THEN
    RAISE EXCEPTION 'published campaign policy is not editor-managed';
  END IF;
  IF OLD.status = 'closed' AND (
     NEW.name IS DISTINCT FROM OLD.name
     OR (NEW.policy_json - 'selected_reviewer_ids')
        IS DISTINCT FROM (OLD.policy_json - 'selected_reviewer_ids')
     OR NEW.review_scope_json IS DISTINCT FROM OLD.review_scope_json
  ) THEN
    RAISE EXCEPTION 'closed campaign inputs are immutable';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION review_platform.protect_review_unit_input() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
      old_campaign_status text;
      new_campaign_status text;
    BEGIN
      IF TG_OP = 'DELETE' THEN
        
        IF EXISTS (
          SELECT 1 FROM review_platform.assignments a
          WHERE a.tenant_id = OLD.tenant_id AND a.review_unit_id = OLD.id
        ) THEN
          RAISE EXCEPTION 'review unit inputs are immutable';
        END IF;
        RETURN OLD;

      END IF;
      IF NEW.campaign_id IS DISTINCT FROM OLD.campaign_id THEN
        SELECT status INTO old_campaign_status FROM review_platform.campaigns
          WHERE tenant_id = OLD.tenant_id AND id = OLD.campaign_id;
        SELECT status INTO new_campaign_status FROM review_platform.campaigns
          WHERE tenant_id = NEW.tenant_id AND id = NEW.campaign_id;
        IF old_campaign_status IS DISTINCT FROM 'pool'
           AND NOT (new_campaign_status = 'pool'
                    AND old_campaign_status IN ('draft', 'planned', 'published')
                    AND NOT EXISTS (
                      SELECT 1 FROM review_platform.assignments a
                      WHERE a.tenant_id = OLD.tenant_id AND a.review_unit_id = OLD.id
                    )) THEN
          RAISE EXCEPTION 'review unit inputs are immutable';
        END IF;
      END IF;
      IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
         OR NEW.review_subject_id IS DISTINCT FROM OLD.review_subject_id
         OR NEW.review_kind IS DISTINCT FROM OLD.review_kind
         OR NEW.question IS DISTINCT FROM OLD.question
         OR NEW.safe_field_label IS DISTINCT FROM OLD.safe_field_label
         OR NEW.input_digest IS DISTINCT FROM OLD.input_digest
         OR NEW.created_at IS DISTINCT FROM OLD.created_at
         OR NEW.extraction_state IS DISTINCT FROM OLD.extraction_state THEN
        RAISE EXCEPTION 'review unit inputs are immutable';
      END IF;
      IF NEW.required_reviews IS DISTINCT FROM OLD.required_reviews
         AND NEW.campaign_id IS NOT DISTINCT FROM OLD.campaign_id THEN
        RAISE EXCEPTION 'review unit inputs are immutable';
      END IF;
      RETURN NEW;
    END;
    $$;

CREATE FUNCTION review_platform.reject_audit_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          RAISE EXCEPTION 'audit events are immutable';
        END;
        $$;

CREATE FUNCTION review_platform.reject_snapshot_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          RAISE EXCEPTION 'review snapshot inputs are immutable';
        END;
        $$;

CREATE TABLE review_platform.adjudication_decisions (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    adjudication_id uuid NOT NULL,
    outcome character varying(60) NOT NULL,
    corrected_value_json jsonb,
    corrected_value_display character varying(10000),
    comment text,
    assessments_json jsonb NOT NULL,
    evidence_ids_json jsonb NOT NULL,
    client_request_id character varying(128) NOT NULL,
    decided_by uuid NOT NULL,
    decided_at timestamp with time zone NOT NULL,
    corrected_provenance_spans_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    preferred_proposal_id uuid,
    CONSTRAINT ck_adjudication_decision_assessments CHECK (((jsonb_typeof(assessments_json) = 'array'::text) AND (jsonb_array_length(assessments_json) >= 2))),
    CONSTRAINT ck_adjudication_decision_comment_required CHECK (((((outcome)::text <> ALL ((ARRAY['both_wrong'::character varying, 'all_wrong'::character varying, 'unsupported_or_not_locatable'::character varying, 'exceptional_skip'::character varying])::text[])) AND (corrected_value_json IS NULL) AND (corrected_value_display IS NULL)) OR (length(btrim(comment)) > 0))),
    CONSTRAINT ck_adjudication_decision_corrected_provenance_spans CHECK ((jsonb_typeof(corrected_provenance_spans_json) = 'array'::text)),
    CONSTRAINT ck_adjudication_decision_outcome CHECK (((outcome)::text = ANY ((ARRAY['candidate_a_preferred'::character varying, 'candidate_b_preferred'::character varying, 'equivalent_supported'::character varying, 'both_wrong'::character varying, 'unsupported_or_not_locatable'::character varying, 'exceptional_skip'::character varying, 'reviewer_assessments_recorded'::character varying, 'reviewer_preferred'::character varying, 'all_equivalent_supported'::character varying, 'all_wrong'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.adjudication_decisions FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.adjudication_drafts (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    adjudication_id uuid NOT NULL,
    decision_json jsonb NOT NULL,
    saved_by uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY review_platform.adjudication_drafts FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.adjudication_participations (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    adjudication_id uuid NOT NULL,
    adjudicator_id uuid NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    assigned_at timestamp with time zone NOT NULL,
    submitted_at timestamp with time zone,
    waived_at timestamp with time zone,
    membership_version integer DEFAULT 0 NOT NULL,
    CONSTRAINT ck_adjudication_participation_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'submitted'::character varying, 'waived'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.adjudication_participations FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.adjudications (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    review_unit_id uuid NOT NULL,
    status character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    assignee_id uuid,
    claimed_at timestamp with time zone,
    CONSTRAINT ck_adjudication_claim CHECK ((((assignee_id IS NULL) AND (claimed_at IS NULL)) OR ((assignee_id IS NOT NULL) AND (claimed_at IS NOT NULL)))),
    CONSTRAINT ck_adjudication_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'resolved'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.adjudications FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.allocation_run_reviewers (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    allocation_run_id uuid NOT NULL,
    reviewer_id uuid NOT NULL,
    planned_assignment_count integer NOT NULL,
    unique_assignment_count integer NOT NULL,
    pairwise_overlap_count integer NOT NULL,
    global_overlap_count integer NOT NULL,
    workload_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY review_platform.allocation_run_reviewers FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.allocation_run_subjects (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    allocation_run_id uuid NOT NULL,
    review_subject_id uuid NOT NULL,
    selection_layer character varying(20) NOT NULL,
    overlap_group_key character varying(120),
    window_index integer,
    metrics_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_run_subject_layer CHECK (((selection_layer)::text = ANY ((ARRAY['global_hub'::character varying, 'pairwise'::character varying, 'rolling'::character varying, 'unique'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.allocation_run_subjects FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.allocation_runs (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    reviewer_pool_id uuid NOT NULL,
    run_key character varying(120) NOT NULL,
    status character varying(20) NOT NULL,
    allocation_policy_version character varying(80) NOT NULL,
    planner_version character varying(80) NOT NULL,
    schema_version character varying(80) NOT NULL,
    source_snapshot_id uuid,
    source_snapshot_digest character varying(64) NOT NULL,
    pool_digest character varying(64) NOT NULL,
    random_seed character varying(200) NOT NULL,
    input_parameters_json jsonb NOT NULL,
    metric_weights_json jsonb NOT NULL,
    feasibility_status character varying(40) NOT NULL,
    feasibility_report_json jsonb NOT NULL,
    summary_json jsonb NOT NULL,
    created_by uuid NOT NULL,
    published_by uuid,
    published_at timestamp with time zone,
    lock_version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    allocation_mode character varying(20) DEFAULT 'initial'::character varying NOT NULL,
    base_allocation_run_id uuid,
    previous_pool_digest character varying(64),
    movement_policy_json jsonb,
    CONSTRAINT ck_allocation_feasibility_status CHECK (((feasibility_status)::text = ANY ((ARRAY['feasible'::character varying, 'feasible_with_warnings'::character varying, 'infeasible'::character varying, 'blocked_by_snapshot_drift'::character varying, 'blocked_by_reviewer_pool'::character varying, 'blocked_by_capacity'::character varying, 'blocked_by_immutable_work'::character varying])::text[]))),
    CONSTRAINT ck_allocation_run_mode CHECK (((allocation_mode)::text = ANY ((ARRAY['initial'::character varying, 'incremental'::character varying])::text[]))),
    CONSTRAINT ck_allocation_run_status CHECK (((status)::text = ANY ((ARRAY['previewed'::character varying, 'planned'::character varying, 'published'::character varying, 'discarded'::character varying, 'superseded'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.allocation_runs FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.annotation_revisions (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    assignment_id uuid NOT NULL,
    revision_no integer NOT NULL,
    state character varying(20) NOT NULL,
    outcome character varying(60) NOT NULL,
    corrected_value_json jsonb,
    corrected_value_display character varying(10000),
    comment text,
    assessments_json jsonb NOT NULL,
    evidence_ids_json jsonb NOT NULL,
    client_request_id character varying(128) NOT NULL,
    author_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_annotation_comment_required CHECK (((((outcome)::text <> ALL ((ARRAY['both_wrong'::character varying, 'unsupported_or_not_locatable'::character varying, 'exceptional_skip'::character varying])::text[])) AND (corrected_value_json IS NULL) AND (corrected_value_display IS NULL)) OR (length(btrim(comment)) > 0))),
    CONSTRAINT ck_annotation_outcome CHECK (((outcome)::text = ANY ((ARRAY['candidate_a_preferred'::character varying, 'candidate_b_preferred'::character varying, 'equivalent_supported'::character varying, 'both_wrong'::character varying, 'unsupported_or_not_locatable'::character varying, 'exceptional_skip'::character varying])::text[]))),
    CONSTRAINT ck_annotation_state CHECK (((state)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying])::text[]))),
    CONSTRAINT ck_annotation_two_assessments CHECK ((jsonb_array_length(assessments_json) = 2))
);

ALTER TABLE ONLY review_platform.annotation_revisions FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.assignment_plans (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    allocation_run_id uuid NOT NULL,
    review_unit_id uuid NOT NULL,
    reviewer_id uuid NOT NULL,
    assignment_id uuid,
    status character varying(20) NOT NULL,
    selection_layer character varying(20) NOT NULL,
    overlap_group_key character varying(120),
    window_index integer,
    plan_metadata_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_assignment_plan_layer CHECK (((selection_layer)::text = ANY ((ARRAY['global_hub'::character varying, 'pairwise'::character varying, 'rolling'::character varying, 'unique'::character varying])::text[]))),
    CONSTRAINT ck_assignment_plan_status CHECK (((status)::text = ANY ((ARRAY['planned'::character varying, 'published'::character varying, 'cancelled'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.assignment_plans FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.assignments (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    review_unit_id uuid NOT NULL,
    reviewer_id uuid NOT NULL,
    status character varying(20) NOT NULL,
    claimed_at timestamp with time zone NOT NULL,
    lease_expires_at timestamp with time zone NOT NULL,
    submitted_at timestamp with time zone,
    lock_version integer NOT NULL,
    revision_requested_at timestamp with time zone,
    revision_requested_by uuid,
    revision_reason character varying(1000),
    CONSTRAINT ck_assignment_status CHECK (((status)::text = ANY ((ARRAY['claimed'::character varying, 'submitted'::character varying, 'released'::character varying, 'revision_requested'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.assignments FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE review_platform.audit_event_sequence
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE review_platform.audit_events (
    id uuid NOT NULL,
    sequence bigint NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    actor_user_id uuid,
    actor_type character varying(40) NOT NULL,
    event_type character varying(100) NOT NULL,
    object_type character varying(80) NOT NULL,
    object_id character varying(100) NOT NULL,
    request_id character varying(64) NOT NULL,
    payload_json jsonb NOT NULL,
    payload_schema_version integer NOT NULL,
    prev_hash character varying(64) NOT NULL,
    event_hash character varying(64) NOT NULL
);

CREATE TABLE review_platform.auth_rate_limits (
    id uuid NOT NULL,
    scope character varying(40) NOT NULL,
    key_digest bytea NOT NULL,
    window_started_at timestamp with time zone NOT NULL,
    attempts integer NOT NULL
);

CREATE TABLE review_platform.campaign_subjects (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    review_subject_id uuid NOT NULL,
    subject_kind character varying(40) NOT NULL,
    review_kind character varying(60) NOT NULL,
    eligibility_status character varying(20) NOT NULL,
    eligibility_reason character varying(300),
    metrics_json jsonb NOT NULL,
    hub_score integer,
    selection_rank integer,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_campaign_subject_status CHECK (((eligibility_status)::text = ANY ((ARRAY['eligible'::character varying, 'excluded'::character varying, 'blocked'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.campaign_subjects FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.campaigns (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    key character varying(100) NOT NULL,
    name character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    policy_version character varying(40) NOT NULL,
    policy_json jsonb NOT NULL,
    manifest_digest character varying(64) NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    subject_kind character varying(40) DEFAULT 'case'::character varying NOT NULL,
    review_kind character varying(60) DEFAULT 'metadata_field'::character varying NOT NULL,
    source_snapshot_id uuid,
    allocation_policy_version character varying(80),
    published_at timestamp with time zone,
    lock_version integer DEFAULT 1 NOT NULL,
    review_scope_json jsonb,
    CONSTRAINT ck_campaign_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'planned'::character varying, 'published'::character varying, 'paused'::character varying, 'closed'::character varying, 'pool'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.campaigns FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.candidates (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    review_unit_id uuid NOT NULL,
    label character varying(1) NOT NULL,
    source_kind character varying(20) NOT NULL,
    verdict character varying(40) NOT NULL,
    value_json jsonb,
    rationale character varying(10000) NOT NULL,
    supporting_quote character varying(10000),
    CONSTRAINT ck_candidate_label CHECK (((label)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying])::text[]))),
    CONSTRAINT ck_candidate_source CHECK (((source_kind)::text = ANY ((ARRAY['deterministic'::character varying, 'model'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.candidates FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.case_submissions (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    case_id character varying(240) NOT NULL,
    reviewer_id uuid NOT NULL,
    submitted_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY review_platform.case_submissions FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.evidence_windows (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    review_unit_id uuid NOT NULL,
    ordinal integer NOT NULL,
    kind character varying(40) NOT NULL,
    snippet character varying(20000) NOT NULL,
    line_start integer,
    line_end integer,
    char_start integer,
    char_end integer,
    source_sha256 character varying(64) NOT NULL,
    provenance_external_id character varying(64),
    body_grounded boolean,
    source_region character varying(40),
    anchor_status character varying(32),
    CONSTRAINT ck_evidence_anchor_status CHECK (((anchor_status IS NULL) OR ((anchor_status)::text = ANY ((ARRAY['anchored'::character varying, 'expected_unanchored'::character varying, 'unexpected_unresolved'::character varying, 'other_document'::character varying])::text[])))),
    CONSTRAINT ck_evidence_char_end CHECK (((char_end IS NULL) OR (char_start IS NULL) OR (char_end >= char_start))),
    CONSTRAINT ck_evidence_char_start CHECK (((char_start IS NULL) OR (char_start >= 0)))
);

ALTER TABLE ONLY review_platform.evidence_windows FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.global_role_grants (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    role_code character varying(40) NOT NULL,
    granted_by uuid,
    reason character varying(500) NOT NULL,
    expires_at timestamp with time zone,
    granted_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    CONSTRAINT ck_global_role CHECK (((role_code)::text = 'super_admin'::text))
);

CREATE TABLE review_platform.idempotency_records (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    operation character varying(160) NOT NULL,
    key_digest character varying(64) NOT NULL,
    request_digest character varying(64) NOT NULL,
    response_json jsonb NOT NULL,
    response_etag character varying(40),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY review_platform.idempotency_records FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.incremental_movement_plans (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    allocation_run_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    from_reviewer_id uuid,
    to_reviewer_id uuid NOT NULL,
    movement_kind character varying(20) NOT NULL,
    movement_reason character varying(80) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_movement_kind CHECK (((movement_kind)::text = ANY ((ARRAY['new'::character varying, 'moved'::character varying, 'preserved'::character varying, 'skipped'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.incremental_movement_plans FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.password_reset_challenges (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_digest bytea NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    attempt_count integer NOT NULL,
    request_source character varying(20) NOT NULL,
    requested_by_user_id uuid,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_password_reset_request_source CHECK (((request_source)::text = ANY ((ARRAY['self_service'::character varying, 'admin'::character varying])::text[])))
);

CREATE TABLE review_platform.proposal_adjudication_items (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    adjudicator_id uuid NOT NULL,
    case_id character varying(240) NOT NULL,
    group_id character varying(60) NOT NULL,
    extracted_adjudication_id uuid,
    proposal_ids_json jsonb NOT NULL,
    origin character varying(20) NOT NULL,
    state character varying(20) NOT NULL,
    lock_version integer NOT NULL,
    draft_json jsonb,
    decision_json jsonb,
    final_value character varying(10000),
    final_provenance_json jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    submitted_at timestamp with time zone,
    CONSTRAINT ck_proposal_adjudication_final CHECK ((((state)::text <> 'submitted'::text) OR ((decision_json IS NOT NULL) AND (submitted_at IS NOT NULL)))),
    CONSTRAINT ck_proposal_adjudication_state CHECK (((state)::text = ANY ((ARRAY['pending'::character varying, 'submitted'::character varying, 'superseded'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.proposal_adjudication_items FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.review_item_answers (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    assignment_id uuid NOT NULL,
    revision_no integer NOT NULL,
    state character varying(20) NOT NULL,
    value_correct boolean,
    provenance_correct boolean,
    corrected_value_json jsonb,
    corrected_value_display character varying(10000),
    comment text,
    failure_reason character varying(80),
    evidence_ids_json jsonb NOT NULL,
    client_request_id character varying(128) NOT NULL,
    author_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    corrected_provenance_spans_json jsonb NOT NULL,
    CONSTRAINT ck_item_answer_failure_reason CHECK (((failure_reason IS NULL) OR (length(btrim((failure_reason)::text)) > 0))),
    CONSTRAINT ck_item_answer_provenance_answered CHECK ((((state)::text = 'draft'::text) OR (provenance_correct IS NOT NULL))),
    CONSTRAINT ck_item_answer_state CHECK (((state)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying])::text[]))),
    CONSTRAINT ck_item_answer_value_answered CHECK ((((state)::text = 'draft'::text) OR (value_correct IS NOT NULL)))
);

ALTER TABLE ONLY review_platform.review_item_answers FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.review_subjects (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    source_snapshot_id uuid NOT NULL,
    subject_kind character varying(40) NOT NULL,
    external_subject_id character varying(100) NOT NULL,
    display_title character varying(300) NOT NULL,
    display_subtitle character varying(300),
    source_version character varying(100),
    primary_source_ref character varying(120) NOT NULL,
    attributes_json jsonb NOT NULL,
    logical_external_item_key text GENERATED ALWAYS AS ((attributes_json ->> 'logical_external_item_key'::text)) STORED,
    snapshot_local_case_external_id text GENERATED ALWAYS AS ((attributes_json ->> 'snapshot_local_case_external_id'::text)) STORED
);

ALTER TABLE ONLY review_platform.review_subjects FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.review_units (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    review_subject_id uuid NOT NULL,
    review_kind character varying(60) NOT NULL,
    question character varying(1000) NOT NULL,
    safe_field_label character varying(160) NOT NULL,
    status character varying(24) NOT NULL,
    required_reviews integer NOT NULL,
    lock_version integer NOT NULL,
    input_digest character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    field_name character varying(120),
    extraction_state character varying(20) DEFAULT 'present'::character varying NOT NULL,
    CONSTRAINT ck_review_unit_extraction_state CHECK (((extraction_state)::text = ANY ((ARRAY['present'::character varying, 'missing'::character varying])::text[]))),
    CONSTRAINT ck_review_unit_required_reviews CHECK ((required_reviews >= 2)),
    CONSTRAINT ck_review_unit_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'in_review'::character varying, 'in_adjudication'::character varying, 'resolved'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.review_units FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.reviewer_added_proposals (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    assignment_id uuid NOT NULL,
    reviewer_id uuid NOT NULL,
    case_id character varying(240) NOT NULL,
    group_id character varying(60) NOT NULL,
    value_schema character varying(60) NOT NULL,
    original_value character varying(10000) NOT NULL,
    value character varying(10000) NOT NULL,
    note character varying(10000) NOT NULL,
    provenance_json jsonb NOT NULL,
    revisions_json jsonb NOT NULL,
    state character varying(20) NOT NULL,
    lock_version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    submitted_at timestamp with time zone,
    CONSTRAINT ck_proposal_state CHECK (((state)::text = ANY ((ARRAY['draft'::character varying, 'submitted'::character varying, 'removed'::character varying])::text[]))),
    CONSTRAINT ck_proposal_submission CHECK ((((state)::text <> 'submitted'::text) OR ((length(btrim((value)::text)) > 0) AND (jsonb_array_length(provenance_json) > 0) AND (submitted_at IS NOT NULL))))
);

ALTER TABLE ONLY review_platform.reviewer_added_proposals FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.reviewer_pool_members (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    reviewer_pool_id uuid NOT NULL,
    reviewer_id uuid NOT NULL,
    eligibility_status character varying(24) NOT NULL,
    exclusion_reason character varying(200),
    workload_limit integer,
    created_at timestamp with time zone NOT NULL,
    capacity_weight double precision DEFAULT '1'::double precision NOT NULL,
    CONSTRAINT ck_reviewer_pool_member_capacity CHECK ((capacity_weight > (0)::double precision)),
    CONSTRAINT ck_reviewer_pool_member_status CHECK (((eligibility_status)::text = ANY ((ARRAY['eligible'::character varying, 'excluded'::character varying, 'inactive'::character varying, 'unauthorized'::character varying, 'conflicted'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.reviewer_pool_members FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.reviewer_pools (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    eligibility_policy_version character varying(80) NOT NULL,
    exclusions_json jsonb NOT NULL,
    pool_digest character varying(64) NOT NULL,
    created_by uuid NOT NULL,
    lock_version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_reviewer_pool_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'closed'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.reviewer_pools FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.role_grants (
    id uuid NOT NULL,
    membership_id uuid NOT NULL,
    role_code character varying(40) NOT NULL,
    granted_by uuid NOT NULL,
    granted_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    CONSTRAINT ck_tenant_role CHECK (((role_code)::text = ANY ((ARRAY['reviewer'::character varying, 'adjudicator'::character varying, 'campaign_manager'::character varying, 'user_admin'::character varying, 'auditor'::character varying])::text[])))
);

CREATE TABLE review_platform.sessions (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_digest bytea NOT NULL,
    csrf_digest bytea NOT NULL,
    authorization_epoch integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    idle_expires_at timestamp with time zone NOT NULL,
    absolute_expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    revocation_reason character varying(120),
    remember_me boolean DEFAULT false NOT NULL
);

CREATE TABLE review_platform.source_render_artifacts (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    source_snapshot_id uuid NOT NULL,
    subject_kind character varying(40) NOT NULL,
    source_system character varying(40) NOT NULL,
    source_kind character varying(40) NOT NULL,
    render_profile character varying(60) NOT NULL,
    render_version integer NOT NULL,
    render_mode character varying(20) NOT NULL,
    content_digest character varying(64) NOT NULL,
    anchor_map_digest character varying(64) NOT NULL,
    object_key character varying(128) NOT NULL,
    artifact_mime_type character varying(80) NOT NULL,
    artifact_size_bytes integer NOT NULL,
    is_current boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    created_by_job character varying(120) NOT NULL,
    CONSTRAINT ck_source_render_anchor_digest CHECK ((char_length((anchor_map_digest)::text) = 64)),
    CONSTRAINT ck_source_render_content_digest CHECK ((char_length((content_digest)::text) = 64)),
    CONSTRAINT ck_source_render_mode CHECK (((render_mode)::text = 'sanitized_html'::text)),
    CONSTRAINT ck_source_render_size_bytes CHECK ((artifact_size_bytes >= 0)),
    CONSTRAINT ck_source_render_version CHECK ((render_version >= 1))
);

ALTER TABLE ONLY review_platform.source_render_artifacts FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.source_snapshots (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    contract_version character varying(80) NOT NULL,
    source_mode character varying(20) NOT NULL,
    source_version character varying(100) NOT NULL,
    external_item_key character varying(240) NOT NULL,
    input_digest character varying(64) NOT NULL,
    imported_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_snapshot_source_mode CHECK (((source_mode)::text = ANY ((ARRAY['synthetic'::character varying, 'dataset'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.source_snapshots FORCE ROW LEVEL SECURITY;

CREATE TABLE review_platform.tenant_memberships (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    status character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_membership_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'active'::character varying, 'suspended'::character varying])::text[])))
);

CREATE TABLE review_platform.tenants (
    id uuid NOT NULL,
    key character varying(80) NOT NULL,
    name character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    lock_version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_tenant_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'suspended'::character varying, 'closed'::character varying])::text[])))
);

CREATE TABLE review_platform.user_activation_challenges (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_digest bytea NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    attempt_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

CREATE TABLE review_platform.users (
    id uuid NOT NULL,
    email_normalized character varying(320) NOT NULL,
    display_name character varying(160) NOT NULL,
    password_hash text,
    status character varying(20) NOT NULL,
    authorization_epoch integer NOT NULL,
    activated_at timestamp with time zone,
    suspended_at timestamp with time zone,
    suspension_reason character varying(500),
    lock_version integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_user_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'active'::character varying, 'suspended'::character varying])::text[])))
);

ALTER TABLE ONLY review_platform.adjudication_decisions
    ADD CONSTRAINT adjudication_decisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.adjudication_drafts
    ADD CONSTRAINT adjudication_drafts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.adjudication_participations
    ADD CONSTRAINT adjudication_participations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.adjudications
    ADD CONSTRAINT adjudications_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.allocation_run_reviewers
    ADD CONSTRAINT allocation_run_reviewers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.allocation_run_subjects
    ADD CONSTRAINT allocation_run_subjects_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.allocation_runs
    ADD CONSTRAINT allocation_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.annotation_revisions
    ADD CONSTRAINT annotation_revisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.assignment_plans
    ADD CONSTRAINT assignment_plans_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.assignments
    ADD CONSTRAINT assignments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.audit_events
    ADD CONSTRAINT audit_events_event_hash_key UNIQUE (event_hash);

ALTER TABLE ONLY review_platform.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.audit_events
    ADD CONSTRAINT audit_events_sequence_key UNIQUE (sequence);

ALTER TABLE ONLY review_platform.auth_rate_limits
    ADD CONSTRAINT auth_rate_limits_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.campaign_subjects
    ADD CONSTRAINT campaign_subjects_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.campaigns
    ADD CONSTRAINT campaigns_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.candidates
    ADD CONSTRAINT candidates_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.case_submissions
    ADD CONSTRAINT case_submissions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.evidence_windows
    ADD CONSTRAINT evidence_windows_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.global_role_grants
    ADD CONSTRAINT global_role_grants_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.idempotency_records
    ADD CONSTRAINT idempotency_records_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.incremental_movement_plans
    ADD CONSTRAINT incremental_movement_plans_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.password_reset_challenges
    ADD CONSTRAINT password_reset_challenges_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.proposal_adjudication_items
    ADD CONSTRAINT proposal_adjudication_items_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.review_item_answers
    ADD CONSTRAINT review_item_answers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.review_subjects
    ADD CONSTRAINT review_subjects_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.review_units
    ADD CONSTRAINT review_units_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.reviewer_added_proposals
    ADD CONSTRAINT reviewer_added_proposals_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.reviewer_pool_members
    ADD CONSTRAINT reviewer_pool_members_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.reviewer_pools
    ADD CONSTRAINT reviewer_pools_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.role_grants
    ADD CONSTRAINT role_grants_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.source_render_artifacts
    ADD CONSTRAINT source_render_artifacts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.source_snapshots
    ADD CONSTRAINT source_snapshots_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.tenant_memberships
    ADD CONSTRAINT tenant_memberships_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.tenants
    ADD CONSTRAINT tenants_key_key UNIQUE (key);

ALTER TABLE ONLY review_platform.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.adjudication_decisions
    ADD CONSTRAINT uq_adjudication_decision_adjudicator UNIQUE (tenant_id, adjudication_id, decided_by);

ALTER TABLE ONLY review_platform.adjudication_drafts
    ADD CONSTRAINT uq_adjudication_draft_adjudicator UNIQUE (tenant_id, adjudication_id, saved_by);

ALTER TABLE ONLY review_platform.adjudication_participations
    ADD CONSTRAINT uq_adjudication_participation_adjudicator UNIQUE (tenant_id, adjudication_id, adjudicator_id);

ALTER TABLE ONLY review_platform.adjudications
    ADD CONSTRAINT uq_adjudication_review_unit UNIQUE (tenant_id, review_unit_id);

ALTER TABLE ONLY review_platform.adjudications
    ADD CONSTRAINT uq_adjudication_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.allocation_runs
    ADD CONSTRAINT uq_allocation_run_key UNIQUE (tenant_id, campaign_id, run_key);

ALTER TABLE ONLY review_platform.allocation_runs
    ADD CONSTRAINT uq_allocation_run_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.annotation_revisions
    ADD CONSTRAINT uq_annotation_request UNIQUE (tenant_id, assignment_id, client_request_id);

ALTER TABLE ONLY review_platform.annotation_revisions
    ADD CONSTRAINT uq_annotation_revision UNIQUE (tenant_id, assignment_id, revision_no);

ALTER TABLE ONLY review_platform.assignment_plans
    ADD CONSTRAINT uq_assignment_plan_reviewer_unit UNIQUE (tenant_id, allocation_run_id, review_unit_id, reviewer_id);

ALTER TABLE ONLY review_platform.assignment_plans
    ADD CONSTRAINT uq_assignment_plan_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.assignments
    ADD CONSTRAINT uq_assignment_reviewer UNIQUE (tenant_id, review_unit_id, reviewer_id);

ALTER TABLE ONLY review_platform.assignments
    ADD CONSTRAINT uq_assignment_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.auth_rate_limits
    ADD CONSTRAINT uq_auth_rate_limit_scope_key UNIQUE (scope, key_digest);

ALTER TABLE ONLY review_platform.campaign_subjects
    ADD CONSTRAINT uq_campaign_subject UNIQUE (tenant_id, campaign_id, review_subject_id);

ALTER TABLE ONLY review_platform.campaign_subjects
    ADD CONSTRAINT uq_campaign_subject_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.campaigns
    ADD CONSTRAINT uq_campaign_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.campaigns
    ADD CONSTRAINT uq_campaign_tenant_key UNIQUE (tenant_id, key);

ALTER TABLE ONLY review_platform.candidates
    ADD CONSTRAINT uq_candidate_label UNIQUE (tenant_id, review_unit_id, label);

ALTER TABLE ONLY review_platform.candidates
    ADD CONSTRAINT uq_candidate_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.case_submissions
    ADD CONSTRAINT uq_case_submission UNIQUE (tenant_id, campaign_id, case_id, reviewer_id);

ALTER TABLE ONLY review_platform.case_submissions
    ADD CONSTRAINT uq_case_submission_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.evidence_windows
    ADD CONSTRAINT uq_evidence_ordinal UNIQUE (tenant_id, review_unit_id, ordinal);

ALTER TABLE ONLY review_platform.evidence_windows
    ADD CONSTRAINT uq_evidence_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.idempotency_records
    ADD CONSTRAINT uq_idempotency_scope UNIQUE (tenant_id, user_id, operation, key_digest);

ALTER TABLE ONLY review_platform.review_item_answers
    ADD CONSTRAINT uq_item_answer_request UNIQUE (tenant_id, assignment_id, client_request_id);

ALTER TABLE ONLY review_platform.review_item_answers
    ADD CONSTRAINT uq_item_answer_revision UNIQUE (tenant_id, assignment_id, revision_no);

ALTER TABLE ONLY review_platform.role_grants
    ADD CONSTRAINT uq_membership_role UNIQUE (membership_id, role_code);

ALTER TABLE ONLY review_platform.tenant_memberships
    ADD CONSTRAINT uq_membership_tenant_user UNIQUE (tenant_id, user_id);

ALTER TABLE ONLY review_platform.incremental_movement_plans
    ADD CONSTRAINT uq_movement_plan_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.review_units
    ADD CONSTRAINT uq_review_unit_input UNIQUE (tenant_id, campaign_id, review_subject_id, review_kind);

ALTER TABLE ONLY review_platform.review_units
    ADD CONSTRAINT uq_review_unit_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.reviewer_pool_members
    ADD CONSTRAINT uq_reviewer_pool_member UNIQUE (tenant_id, reviewer_pool_id, reviewer_id);

ALTER TABLE ONLY review_platform.reviewer_pool_members
    ADD CONSTRAINT uq_reviewer_pool_member_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.reviewer_pools
    ADD CONSTRAINT uq_reviewer_pool_name UNIQUE (tenant_id, campaign_id, name);

ALTER TABLE ONLY review_platform.reviewer_pools
    ADD CONSTRAINT uq_reviewer_pool_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.allocation_run_reviewers
    ADD CONSTRAINT uq_run_reviewer UNIQUE (tenant_id, allocation_run_id, reviewer_id);

ALTER TABLE ONLY review_platform.allocation_run_reviewers
    ADD CONSTRAINT uq_run_reviewer_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.allocation_run_subjects
    ADD CONSTRAINT uq_run_subject UNIQUE (tenant_id, allocation_run_id, review_subject_id);

ALTER TABLE ONLY review_platform.allocation_run_subjects
    ADD CONSTRAINT uq_run_subject_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.source_snapshots
    ADD CONSTRAINT uq_snapshot_external_item UNIQUE (tenant_id, external_item_key);

ALTER TABLE ONLY review_platform.source_snapshots
    ADD CONSTRAINT uq_snapshot_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.source_render_artifacts
    ADD CONSTRAINT uq_source_render_artifact_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.review_subjects
    ADD CONSTRAINT uq_subject_snapshot UNIQUE (tenant_id, source_snapshot_id);

ALTER TABLE ONLY review_platform.review_subjects
    ADD CONSTRAINT uq_subject_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY review_platform.global_role_grants
    ADD CONSTRAINT uq_user_global_role UNIQUE (user_id, role_code);

ALTER TABLE ONLY review_platform.user_activation_challenges
    ADD CONSTRAINT user_activation_challenges_pkey PRIMARY KEY (id);

ALTER TABLE ONLY review_platform.users
    ADD CONSTRAINT users_email_normalized_key UNIQUE (email_normalized);

ALTER TABLE ONLY review_platform.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

CREATE UNIQUE INDEX ix_activation_token_digest ON review_platform.user_activation_challenges USING btree (token_digest);

CREATE INDEX ix_adjudication_participation_user_status ON review_platform.adjudication_participations USING btree (tenant_id, adjudicator_id, status, adjudication_id);

CREATE INDEX ix_adjudications_tenant_unit ON review_platform.adjudications USING btree (tenant_id, review_unit_id);

CREATE INDEX ix_allocation_run_campaign_status ON review_platform.allocation_runs USING btree (tenant_id, campaign_id, status);

CREATE INDEX ix_allocation_run_subjects_tenant_subject ON review_platform.allocation_run_subjects USING btree (tenant_id, review_subject_id);

CREATE INDEX ix_allocation_runs_tenant_snapshot ON review_platform.allocation_runs USING btree (tenant_id, source_snapshot_id);

CREATE INDEX ix_assignment_plan_assignment ON review_platform.assignment_plans USING btree (tenant_id, assignment_id);

CREATE INDEX ix_assignment_plan_reviewer ON review_platform.assignment_plans USING btree (tenant_id, reviewer_id, status);

CREATE INDEX ix_assignment_plan_run_status ON review_platform.assignment_plans USING btree (tenant_id, allocation_run_id, status);

CREATE INDEX ix_assignment_plans_tenant_unit ON review_platform.assignment_plans USING btree (tenant_id, review_unit_id);

CREATE INDEX ix_assignment_reviewer ON review_platform.assignments USING btree (tenant_id, reviewer_id, status);

CREATE INDEX ix_audit_actor_occurred ON review_platform.audit_events USING btree (actor_user_id, occurred_at);

CREATE INDEX ix_audit_object_occurred ON review_platform.audit_events USING btree (object_type, object_id, occurred_at);

CREATE INDEX ix_campaign_subject_rank ON review_platform.campaign_subjects USING btree (tenant_id, campaign_id, selection_rank, id);

CREATE INDEX ix_campaign_subjects_tenant_subject ON review_platform.campaign_subjects USING btree (tenant_id, review_subject_id);

CREATE INDEX ix_campaign_tenant_subject_kind ON review_platform.campaigns USING btree (tenant_id, subject_kind, review_kind, status);

CREATE INDEX ix_campaigns_tenant_snapshot ON review_platform.campaigns USING btree (tenant_id, source_snapshot_id);

CREATE INDEX ix_candidates_tenant_unit ON review_platform.candidates USING btree (tenant_id, review_unit_id);

CREATE INDEX ix_case_submission_campaign ON review_platform.case_submissions USING btree (tenant_id, campaign_id);

CREATE INDEX ix_evidence_windows_tenant_anchor_status ON review_platform.evidence_windows USING btree (tenant_id, anchor_status);

CREATE INDEX ix_evidence_windows_tenant_unit ON review_platform.evidence_windows USING btree (tenant_id, review_unit_id);

CREATE INDEX ix_movement_plan_run ON review_platform.incremental_movement_plans USING btree (tenant_id, allocation_run_id, movement_kind);

CREATE UNIQUE INDEX ix_password_reset_token_digest ON review_platform.password_reset_challenges USING btree (token_digest);

CREATE INDEX ix_proposal_adjudicator_case ON review_platform.proposal_adjudication_items USING btree (tenant_id, campaign_id, case_id, adjudicator_id);

CREATE INDEX ix_proposal_assignment ON review_platform.reviewer_added_proposals USING btree (tenant_id, assignment_id);

CREATE INDEX ix_proposal_owner_case ON review_platform.reviewer_added_proposals USING btree (tenant_id, campaign_id, reviewer_id, case_id);

CREATE INDEX ix_review_unit_queue ON review_platform.review_units USING btree (tenant_id, status, created_at, id);

CREATE INDEX ix_review_units_tenant_subject ON review_platform.review_units USING btree (tenant_id, review_subject_id);

CREATE INDEX ix_reviewer_pool_member_reviewer ON review_platform.reviewer_pool_members USING btree (tenant_id, reviewer_id);

CREATE INDEX ix_run_reviewer_reviewer ON review_platform.allocation_run_reviewers USING btree (tenant_id, reviewer_id);

CREATE INDEX ix_run_subject_layer ON review_platform.allocation_run_subjects USING btree (tenant_id, allocation_run_id, selection_layer, id);

CREATE UNIQUE INDEX ix_session_token_digest ON review_platform.sessions USING btree (token_digest);

CREATE INDEX ix_source_render_artifacts_tenant_snapshot ON review_platform.source_render_artifacts USING btree (tenant_id, source_snapshot_id);

CREATE INDEX ix_subject_logical_external_item ON review_platform.review_subjects USING btree (tenant_id, ((attributes_json ->> 'logical_external_item_key'::text)));

CREATE INDEX ix_subject_logical_key_col ON review_platform.review_subjects USING btree (tenant_id, logical_external_item_key);

CREATE INDEX ix_subject_snapshot_case_col ON review_platform.review_subjects USING btree (tenant_id, snapshot_local_case_external_id);

CREATE INDEX ix_subject_snapshot_local_case ON review_platform.review_subjects USING btree (tenant_id, ((attributes_json ->> 'snapshot_local_case_external_id'::text)));

CREATE UNIQUE INDEX uq_proposal_extracted_target ON review_platform.proposal_adjudication_items USING btree (tenant_id, adjudicator_id, extracted_adjudication_id) WHERE ((state)::text <> 'superseded'::text);

CREATE UNIQUE INDEX uq_source_render_artifact_current ON review_platform.source_render_artifacts USING btree (tenant_id, source_snapshot_id) WHERE is_current;

CREATE TRIGGER adjudication_decisions_immutable BEFORE DELETE OR UPDATE ON review_platform.adjudication_decisions FOR EACH ROW EXECUTE FUNCTION review_platform.reject_snapshot_mutation();

CREATE TRIGGER annotation_revisions_immutable BEFORE DELETE OR UPDATE ON review_platform.annotation_revisions FOR EACH ROW EXECUTE FUNCTION review_platform.reject_snapshot_mutation();

CREATE TRIGGER audit_events_immutable BEFORE DELETE OR UPDATE ON review_platform.audit_events FOR EACH ROW EXECUTE FUNCTION review_platform.reject_audit_mutation();

CREATE TRIGGER campaign_review_count_frozen BEFORE UPDATE ON review_platform.campaigns FOR EACH ROW EXECUTE FUNCTION review_platform.freeze_published_review_count();

CREATE TRIGGER campaigns_allocation_state_guard BEFORE DELETE OR UPDATE ON review_platform.campaigns FOR EACH ROW EXECUTE FUNCTION review_platform.protect_campaign_allocation_state();

CREATE TRIGGER candidates_immutable BEFORE UPDATE ON review_platform.candidates FOR EACH ROW EXECUTE FUNCTION review_platform.reject_snapshot_mutation();

CREATE TRIGGER case_submissions_immutable BEFORE DELETE OR UPDATE ON review_platform.case_submissions FOR EACH ROW EXECUTE FUNCTION review_platform.reject_snapshot_mutation();

CREATE TRIGGER evidence_windows_immutable BEFORE UPDATE ON review_platform.evidence_windows FOR EACH ROW EXECUTE FUNCTION review_platform.reject_snapshot_mutation();

CREATE TRIGGER proposal_adjudication_immutable BEFORE DELETE OR UPDATE ON review_platform.proposal_adjudication_items FOR EACH ROW EXECUTE FUNCTION review_platform.guard_proposal_adjudication_item();

CREATE TRIGGER proposal_immutable BEFORE DELETE OR UPDATE ON review_platform.reviewer_added_proposals FOR EACH ROW EXECUTE FUNCTION review_platform.guard_reviewer_proposal();

CREATE TRIGGER review_item_answers_immutable BEFORE DELETE OR UPDATE ON review_platform.review_item_answers FOR EACH ROW EXECUTE FUNCTION review_platform.reject_snapshot_mutation();

CREATE TRIGGER review_subjects_immutable BEFORE UPDATE ON review_platform.review_subjects FOR EACH ROW EXECUTE FUNCTION review_platform.reject_snapshot_mutation();

CREATE TRIGGER review_units_input_immutable BEFORE DELETE OR UPDATE ON review_platform.review_units FOR EACH ROW EXECUTE FUNCTION review_platform.protect_review_unit_input();

CREATE TRIGGER source_render_artifacts_immutable BEFORE UPDATE ON review_platform.source_render_artifacts FOR EACH ROW EXECUTE FUNCTION review_platform.reject_snapshot_mutation();

CREATE TRIGGER source_snapshots_immutable BEFORE UPDATE ON review_platform.source_snapshots FOR EACH ROW EXECUTE FUNCTION review_platform.reject_snapshot_mutation();

ALTER TABLE ONLY review_platform.adjudication_decisions
    ADD CONSTRAINT adjudication_decisions_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.adjudication_decisions
    ADD CONSTRAINT adjudication_decisions_tenant_id_adjudication_id_fkey FOREIGN KEY (tenant_id, adjudication_id) REFERENCES review_platform.adjudications(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.adjudication_decisions
    ADD CONSTRAINT adjudication_decisions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES review_platform.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.adjudication_drafts
    ADD CONSTRAINT adjudication_drafts_saved_by_fkey FOREIGN KEY (saved_by) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.adjudication_drafts
    ADD CONSTRAINT adjudication_drafts_tenant_id_adjudication_id_fkey FOREIGN KEY (tenant_id, adjudication_id) REFERENCES review_platform.adjudications(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.adjudication_participations
    ADD CONSTRAINT adjudication_participations_adjudicator_id_fkey FOREIGN KEY (adjudicator_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.adjudication_participations
    ADD CONSTRAINT adjudication_participations_tenant_id_adjudication_id_fkey FOREIGN KEY (tenant_id, adjudication_id) REFERENCES review_platform.adjudications(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.adjudications
    ADD CONSTRAINT adjudications_tenant_id_review_unit_id_fkey FOREIGN KEY (tenant_id, review_unit_id) REFERENCES review_platform.review_units(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.allocation_run_reviewers
    ADD CONSTRAINT allocation_run_reviewers_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.allocation_run_reviewers
    ADD CONSTRAINT allocation_run_reviewers_tenant_id_allocation_run_id_fkey FOREIGN KEY (tenant_id, allocation_run_id) REFERENCES review_platform.allocation_runs(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.allocation_run_subjects
    ADD CONSTRAINT allocation_run_subjects_tenant_id_allocation_run_id_fkey FOREIGN KEY (tenant_id, allocation_run_id) REFERENCES review_platform.allocation_runs(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.allocation_run_subjects
    ADD CONSTRAINT allocation_run_subjects_tenant_id_review_subject_id_fkey FOREIGN KEY (tenant_id, review_subject_id) REFERENCES review_platform.review_subjects(tenant_id, id) ON DELETE RESTRICT;

ALTER TABLE ONLY review_platform.allocation_runs
    ADD CONSTRAINT allocation_runs_created_by_fkey FOREIGN KEY (created_by) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.allocation_runs
    ADD CONSTRAINT allocation_runs_published_by_fkey FOREIGN KEY (published_by) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.allocation_runs
    ADD CONSTRAINT allocation_runs_tenant_id_campaign_id_fkey FOREIGN KEY (tenant_id, campaign_id) REFERENCES review_platform.campaigns(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.allocation_runs
    ADD CONSTRAINT allocation_runs_tenant_id_reviewer_pool_id_fkey FOREIGN KEY (tenant_id, reviewer_pool_id) REFERENCES review_platform.reviewer_pools(tenant_id, id) ON DELETE RESTRICT;

ALTER TABLE ONLY review_platform.allocation_runs
    ADD CONSTRAINT allocation_runs_tenant_id_source_snapshot_id_fkey FOREIGN KEY (tenant_id, source_snapshot_id) REFERENCES review_platform.source_snapshots(tenant_id, id);

ALTER TABLE ONLY review_platform.annotation_revisions
    ADD CONSTRAINT annotation_revisions_author_id_fkey FOREIGN KEY (author_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.annotation_revisions
    ADD CONSTRAINT annotation_revisions_tenant_id_assignment_id_fkey FOREIGN KEY (tenant_id, assignment_id) REFERENCES review_platform.assignments(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.assignment_plans
    ADD CONSTRAINT assignment_plans_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.assignment_plans
    ADD CONSTRAINT assignment_plans_tenant_id_allocation_run_id_fkey FOREIGN KEY (tenant_id, allocation_run_id) REFERENCES review_platform.allocation_runs(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.assignment_plans
    ADD CONSTRAINT assignment_plans_tenant_id_assignment_id_fkey FOREIGN KEY (tenant_id, assignment_id) REFERENCES review_platform.assignments(tenant_id, id) ON DELETE SET NULL;

ALTER TABLE ONLY review_platform.assignment_plans
    ADD CONSTRAINT assignment_plans_tenant_id_review_unit_id_fkey FOREIGN KEY (tenant_id, review_unit_id) REFERENCES review_platform.review_units(tenant_id, id) ON DELETE RESTRICT;

ALTER TABLE ONLY review_platform.assignments
    ADD CONSTRAINT assignments_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.assignments
    ADD CONSTRAINT assignments_revision_requested_by_fkey FOREIGN KEY (revision_requested_by) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.assignments
    ADD CONSTRAINT assignments_tenant_id_review_unit_id_fkey FOREIGN KEY (tenant_id, review_unit_id) REFERENCES review_platform.review_units(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.campaign_subjects
    ADD CONSTRAINT campaign_subjects_tenant_id_campaign_id_fkey FOREIGN KEY (tenant_id, campaign_id) REFERENCES review_platform.campaigns(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.campaign_subjects
    ADD CONSTRAINT campaign_subjects_tenant_id_review_subject_id_fkey FOREIGN KEY (tenant_id, review_subject_id) REFERENCES review_platform.review_subjects(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.campaigns
    ADD CONSTRAINT campaigns_created_by_fkey FOREIGN KEY (created_by) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.campaigns
    ADD CONSTRAINT campaigns_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES review_platform.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.candidates
    ADD CONSTRAINT candidates_tenant_id_review_unit_id_fkey FOREIGN KEY (tenant_id, review_unit_id) REFERENCES review_platform.review_units(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.case_submissions
    ADD CONSTRAINT case_submissions_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.case_submissions
    ADD CONSTRAINT case_submissions_tenant_id_campaign_id_fkey FOREIGN KEY (tenant_id, campaign_id) REFERENCES review_platform.campaigns(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.evidence_windows
    ADD CONSTRAINT evidence_windows_tenant_id_review_unit_id_fkey FOREIGN KEY (tenant_id, review_unit_id) REFERENCES review_platform.review_units(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.adjudications
    ADD CONSTRAINT fk_adjudication_assignee FOREIGN KEY (assignee_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.allocation_runs
    ADD CONSTRAINT fk_allocation_run_base FOREIGN KEY (base_allocation_run_id) REFERENCES review_platform.allocation_runs(id) ON DELETE RESTRICT;

ALTER TABLE ONLY review_platform.campaigns
    ADD CONSTRAINT fk_campaign_source_snapshot FOREIGN KEY (tenant_id, source_snapshot_id) REFERENCES review_platform.source_snapshots(tenant_id, id);

ALTER TABLE ONLY review_platform.adjudication_decisions
    ADD CONSTRAINT fk_decision_preferred_proposal FOREIGN KEY (preferred_proposal_id) REFERENCES review_platform.reviewer_added_proposals(id);

ALTER TABLE ONLY review_platform.global_role_grants
    ADD CONSTRAINT global_role_grants_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.global_role_grants
    ADD CONSTRAINT global_role_grants_user_id_fkey FOREIGN KEY (user_id) REFERENCES review_platform.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.idempotency_records
    ADD CONSTRAINT idempotency_records_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES review_platform.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.idempotency_records
    ADD CONSTRAINT idempotency_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES review_platform.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.incremental_movement_plans
    ADD CONSTRAINT incremental_movement_plans_tenant_id_allocation_run_id_fkey FOREIGN KEY (tenant_id, allocation_run_id) REFERENCES review_platform.allocation_runs(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.password_reset_challenges
    ADD CONSTRAINT password_reset_challenges_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.password_reset_challenges
    ADD CONSTRAINT password_reset_challenges_user_id_fkey FOREIGN KEY (user_id) REFERENCES review_platform.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.proposal_adjudication_items
    ADD CONSTRAINT proposal_adjudication_items_adjudicator_id_fkey FOREIGN KEY (adjudicator_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.proposal_adjudication_items
    ADD CONSTRAINT proposal_adjudication_items_tenant_id_campaign_id_fkey FOREIGN KEY (tenant_id, campaign_id) REFERENCES review_platform.campaigns(tenant_id, id);

ALTER TABLE ONLY review_platform.proposal_adjudication_items
    ADD CONSTRAINT proposal_adjudication_items_tenant_id_extracted_adjudicati_fkey FOREIGN KEY (tenant_id, extracted_adjudication_id) REFERENCES review_platform.adjudications(tenant_id, id);

ALTER TABLE ONLY review_platform.review_item_answers
    ADD CONSTRAINT review_item_answers_author_id_fkey FOREIGN KEY (author_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.review_item_answers
    ADD CONSTRAINT review_item_answers_tenant_id_assignment_id_fkey FOREIGN KEY (tenant_id, assignment_id) REFERENCES review_platform.assignments(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.review_subjects
    ADD CONSTRAINT review_subjects_tenant_id_source_snapshot_id_fkey FOREIGN KEY (tenant_id, source_snapshot_id) REFERENCES review_platform.source_snapshots(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.review_units
    ADD CONSTRAINT review_units_tenant_id_campaign_id_fkey FOREIGN KEY (tenant_id, campaign_id) REFERENCES review_platform.campaigns(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.review_units
    ADD CONSTRAINT review_units_tenant_id_review_subject_id_fkey FOREIGN KEY (tenant_id, review_subject_id) REFERENCES review_platform.review_subjects(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.reviewer_added_proposals
    ADD CONSTRAINT reviewer_added_proposals_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.reviewer_added_proposals
    ADD CONSTRAINT reviewer_added_proposals_tenant_id_assignment_id_fkey FOREIGN KEY (tenant_id, assignment_id) REFERENCES review_platform.assignments(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.reviewer_added_proposals
    ADD CONSTRAINT reviewer_added_proposals_tenant_id_campaign_id_fkey FOREIGN KEY (tenant_id, campaign_id) REFERENCES review_platform.campaigns(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.reviewer_pool_members
    ADD CONSTRAINT reviewer_pool_members_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.reviewer_pool_members
    ADD CONSTRAINT reviewer_pool_members_tenant_id_reviewer_pool_id_fkey FOREIGN KEY (tenant_id, reviewer_pool_id) REFERENCES review_platform.reviewer_pools(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.reviewer_pools
    ADD CONSTRAINT reviewer_pools_created_by_fkey FOREIGN KEY (created_by) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.reviewer_pools
    ADD CONSTRAINT reviewer_pools_tenant_id_campaign_id_fkey FOREIGN KEY (tenant_id, campaign_id) REFERENCES review_platform.campaigns(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.role_grants
    ADD CONSTRAINT role_grants_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES review_platform.users(id);

ALTER TABLE ONLY review_platform.role_grants
    ADD CONSTRAINT role_grants_membership_id_fkey FOREIGN KEY (membership_id) REFERENCES review_platform.tenant_memberships(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES review_platform.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.source_render_artifacts
    ADD CONSTRAINT source_render_artifacts_tenant_id_source_snapshot_id_fkey FOREIGN KEY (tenant_id, source_snapshot_id) REFERENCES review_platform.source_snapshots(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.source_snapshots
    ADD CONSTRAINT source_snapshots_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES review_platform.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.tenant_memberships
    ADD CONSTRAINT tenant_memberships_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES review_platform.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.tenant_memberships
    ADD CONSTRAINT tenant_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES review_platform.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY review_platform.user_activation_challenges
    ADD CONSTRAINT user_activation_challenges_user_id_fkey FOREIGN KEY (user_id) REFERENCES review_platform.users(id) ON DELETE CASCADE;

ALTER TABLE review_platform.adjudication_decisions ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.adjudication_drafts ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.adjudication_participations ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.adjudications ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.allocation_run_reviewers ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.allocation_run_subjects ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.allocation_runs ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.annotation_revisions ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.assignment_plans ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.assignments ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.campaign_subjects ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.campaigns ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.candidates ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.case_submissions ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.evidence_windows ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.idempotency_records ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.incremental_movement_plans ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.proposal_adjudication_items ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.review_item_answers ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.review_subjects ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.review_units ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.reviewer_added_proposals ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.reviewer_pool_members ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.reviewer_pools ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.source_render_artifacts ENABLE ROW LEVEL SECURITY;

ALTER TABLE review_platform.source_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON review_platform.adjudication_decisions USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.adjudication_drafts USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.adjudication_participations USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.adjudications USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.allocation_run_reviewers USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.allocation_run_subjects USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.allocation_runs USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.annotation_revisions USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.assignment_plans USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.assignments USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.campaign_subjects USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.campaigns USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.candidates USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.case_submissions USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.evidence_windows USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.idempotency_records USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.incremental_movement_plans USING ((tenant_id = ( SELECT tenants.id
   FROM review_platform.tenants
  WHERE (tenants.id = (current_setting('review_platform.tenant_id'::text, true))::uuid))));

CREATE POLICY tenant_isolation ON review_platform.proposal_adjudication_items USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.review_item_answers USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.review_subjects USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.review_units USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.reviewer_added_proposals USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.reviewer_pool_members USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.reviewer_pools USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.source_render_artifacts USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));

CREATE POLICY tenant_isolation ON review_platform.source_snapshots USING ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('review_platform.tenant_id'::text, true), ''::text))::uuid));
