CREATE TABLE employees (
  emplid     text PRIMARY KEY,
  qr_data    text NOT NULL UNIQUE,
  name       text NOT NULL,
  active     boolean NOT NULL DEFAULT true,
  synced_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE referrers (
  tg_user_id     bigint PRIMARY KEY,
  emplid         text NOT NULL UNIQUE REFERENCES employees(emplid),
  tg_username    text,
  verify_method  text NOT NULL CHECK (verify_method IN ('qr', 'manual_id', 'admin')),
  verified_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  tg_user_id      bigint PRIMARY KEY,
  language        text CHECK (language IN ('ru', 'en')),
  step            text NOT NULL,
  data            jsonb NOT NULL DEFAULT '{}',
  submission_key  uuid,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE referrals (
  id                   bigserial PRIMARY KEY,
  submission_key       uuid NOT NULL UNIQUE,
  first_name           text NOT NULL,
  last_name            text NOT NULL,
  phone                text NOT NULL UNIQUE CHECK (phone ~ '^\+[1-9][0-9]{6,14}$'),
  email                text NOT NULL UNIQUE CHECK (email = lower(email)),
  worked_before        boolean NOT NULL,
  referrer_tg_user_id  bigint NOT NULL,
  referrer_emplid      text NOT NULL REFERENCES employees(emplid),
  referrer_name        text NOT NULL,
  photo_file_id        text NOT NULL,
  photo_kind           text NOT NULL CHECK (photo_kind IN ('photo', 'document')),
  photo_url            text,
  hr_data              jsonb NOT NULL DEFAULT '{}',
  created_at           timestamptz NOT NULL DEFAULT now(),
  sheet_synced_at      timestamptz,
  hr_notified_at       timestamptz
);

CREATE INDEX referrals_sheet_pending ON referrals (id) WHERE sheet_synced_at IS NULL;
CREATE INDEX referrals_notify_pending ON referrals (id) WHERE hr_notified_at IS NULL;

CREATE TABLE referral_photos (
  referral_id  bigint PRIMARY KEY REFERENCES referrals(id),
  content      bytea NOT NULL,
  mime_type    text NOT NULL,
  size_bytes   integer NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 20971520),
  sha256       text NOT NULL
);
