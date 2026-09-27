-- Отзыв заявки сотрудником: заявка остаётся, телефон и почта освобождаются.
ALTER TABLE referrals ADD COLUMN withdrawn_at timestamptz;
ALTER TABLE referrals DROP CONSTRAINT referrals_phone_key;
ALTER TABLE referrals DROP CONSTRAINT referrals_email_key;
CREATE UNIQUE INDEX referrals_phone_active ON referrals (phone) WHERE withdrawn_at IS NULL;
CREATE UNIQUE INDEX referrals_email_active ON referrals (email) WHERE withdrawn_at IS NULL;
