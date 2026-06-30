-- Affection bot data — separate database from portfolio.
-- Source of truth for affection_conversation + affection_outbox.
-- Owned by affection_user; no other role has access to this database.

CREATE TABLE IF NOT EXISTS affection_conversation (
    id integer NOT NULL,
    chat_id text NOT NULL,
    role text NOT NULL,
    content text,
    tool_calls jsonb,
    tool_call_id text,
    created_at timestamp with time zone DEFAULT now()
);
ALTER TABLE affection_conversation OWNER TO affection_user;

CREATE SEQUENCE IF NOT EXISTS affection_conversation_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE affection_conversation_id_seq OWNER TO affection_user;
ALTER SEQUENCE affection_conversation_id_seq OWNED BY affection_conversation.id;

ALTER TABLE ONLY affection_conversation ALTER COLUMN id SET DEFAULT nextval('affection_conversation_id_seq'::regclass);
ALTER TABLE ONLY affection_conversation ADD CONSTRAINT affection_conversation_pkey PRIMARY KEY (id);
CREATE INDEX IF NOT EXISTS idx_affection_cnv_chat ON affection_conversation USING btree (chat_id, created_at);

CREATE TABLE IF NOT EXISTS affection_outbox (
    id integer NOT NULL,
    sent_at timestamp with time zone DEFAULT now() NOT NULL,
    recipient_id text NOT NULL,
    sticker_pack text,
    sticker_file_id text NOT NULL,
    caption text,
    llm_model text,
    delivered boolean,
    error text
);
ALTER TABLE affection_outbox OWNER TO affection_user;

CREATE SEQUENCE IF NOT EXISTS affection_outbox_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE affection_outbox_id_seq OWNER TO affection_user;
ALTER SEQUENCE affection_outbox_id_seq OWNED BY affection_outbox.id;

ALTER TABLE ONLY affection_outbox ALTER COLUMN id SET DEFAULT nextval('affection_outbox_id_seq'::regclass);
ALTER TABLE ONLY affection_outbox ADD CONSTRAINT affection_outbox_pkey PRIMARY KEY (id);
CREATE INDEX IF NOT EXISTS idx_affection_outbox_sent_at ON affection_outbox USING btree (sent_at DESC);
