EXTENSION = chainsql
DATA = chainsql--0.1.0.sql chainsql--0.1.0--0.2.0.sql chainsql--0.2.0--0.2.1.sql chainsql--0.2.1--0.3.0.sql chainsql--0.3.0--0.4.0.sql
PG_CONFIG ?= pg_config
PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)
