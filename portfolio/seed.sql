-- Example data. Replace with real positions before use.
-- Tickers normalised to yfinance format: HKG:XXXX -> XXXX.HK

INSERT INTO portfolio_positions (ticker, company_name, shares, currency, consolidation_group) VALUES
    ('META',    'Meta Platforms Inc',                    100,  'USD', NULL),
    ('AMZN',    'Amazon.com Inc',                        100,  'USD', NULL),
    ('GOOGL',   'Alphabet Inc Class A',                  100,  'USD', NULL),
    ('9988.HK', 'Alibaba Group Holding Ltd',             100,  'HKD', 'Alibaba'),
    ('BRK-B',   'Berkshire Hathaway Inc Class B',        100,  'USD', NULL),
    ('BABA',    'Alibaba Group Holding Ltd - ADR',       100,  'USD', 'Alibaba'),
    ('UBER',    'Uber Technologies Inc',                 100,  'USD', NULL),
    ('NVDA',    'NVIDIA Corp',                           100,  'USD', NULL),
    ('WIX',     'Wix.Com Ltd',                           100,  'USD', NULL),
    ('0700.HK', 'Tencent Holdings Ltd',                  100,  'HKD', NULL),
    ('XLV',     'Health Care Select Sector SPDR',        100,  'USD', NULL),
    ('ADBE',    'Adobe Inc',                             100,  'USD', NULL),
    ('TSM',     'Taiwan Semiconductor Mfg Co Ltd',       100,  'USD', NULL),
    ('PYPL',    'PayPal Holdings Inc',                   100,  'USD', NULL),
    ('CRM',     'Salesforce Inc',                        100,  'USD', NULL),
    ('RDDT',    'Reddit Inc',                            100,  'USD', NULL),
    ('NTES',    'NetEase Inc',                           100,  'USD', NULL),
    ('ADM',     'Archer-Daniels-Midland Co',             100,  'USD', NULL),
    ('3690.HK', 'Meituan',                               100,  'HKD', NULL),
    ('PINS',    'Pinterest Inc',                         100,  'USD', NULL),
    ('QCOM',    'Qualcomm Inc',                          100,  'USD', NULL),
    ('AMAT',    'Applied Materials Inc',                 100,  'USD', NULL),
    ('9888.HK', 'Baidu Inc',                             100,  'HKD', 'Baidu'),
    ('CRWV',    'CoreWeave Inc',                         100,  'USD', NULL),
    ('AMD',     'Advanced Micro Devices Inc',            100,  'USD', NULL),
    ('TCOM',    'Trip.com Group Ltd',                    100,  'USD', NULL),
    ('V',       'Visa Inc',                              100,  'USD', NULL),
    ('BIDU',    'Baidu Inc',                             100,  'USD', 'Baidu'),
    ('NVO',     'Novo Nordisk A/S',                      100,  'USD', NULL),
    ('EQNR',    'Equinor ASA',                           100,  'USD', NULL),
    ('SERV',    'Serve Robotics Inc',                    100,  'USD', NULL),
    ('MSFT',    'Microsoft Corp',                        100,  'USD', NULL),
    ('GRAB',    'Grab Holdings Ltd',                     100,  'USD', NULL)
ON CONFLICT (ticker) DO NOTHING;

-- Set consolidation_group for ADR pairs (for rows that already exist in DB)
UPDATE portfolio_positions SET consolidation_group = 'Alibaba' WHERE ticker IN ('BABA', '9988.HK') AND consolidation_group IS NULL;
UPDATE portfolio_positions SET consolidation_group = 'Baidu'   WHERE ticker IN ('BIDU', '9888.HK') AND consolidation_group IS NULL;
