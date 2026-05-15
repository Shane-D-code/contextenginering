#!/usr/bin/env bash
# validate_submission.sh — Pre-submission validation
# Run this before submitting to catch all issues.

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

ok()   { echo -e "${GREEN}✅ $1${NC}"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}❌ $1${NC}"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }

echo "=========================================="
echo " Mini Anvil P-02 — Submission Validator"
echo "=========================================="
echo ""

echo "─── Critical Files ───────────────────────"
[ -f "bench/run.sh" ]           && ok "bench/run.sh exists"         || fail "bench/run.sh MISSING"
[ -f "Dockerfile" ]             && ok "Dockerfile exists"           || fail "Dockerfile MISSING"
[ -f "requirements.txt" ]       && ok "requirements.txt exists"     || fail "requirements.txt MISSING"
[ -f "README.md" ]              && ok "README.md exists"            || fail "README.md MISSING"
[ -f "self_check.py" ]          && ok "self_check.py exists"        || fail "self_check.py MISSING"
[ -f "run.py" ]                 && ok "run.py exists"               || fail "run.py MISSING"
[ -f "adapters/engine.py" ]     && ok "adapters/engine.py exists"   || fail "adapters/engine.py MISSING"

echo ""
echo "─── Test Suite ───────────────────────────"
[ -f "tests/__init__.py" ]                          && ok "tests/__init__.py"   || fail "tests/__init__.py MISSING"
[ -f "tests/test_identity.py" ]                     && ok "test_identity.py"    || fail "test_identity.py MISSING"
[ -f "tests/test_store.py" ]                        && ok "test_store.py"       || fail "test_store.py MISSING"
[ -f "tests/test_graph.py" ]                        && ok "test_graph.py"       || fail "test_graph.py MISSING"
[ -f "tests/test_motifs.py" ]                       && ok "test_motifs.py"      || fail "test_motifs.py MISSING"
[ -f "tests/test_assembler.py" ]                    && ok "test_assembler.py"   || fail "test_assembler.py MISSING"
[ -f "tests/test_adapter.py" ]                      && ok "test_adapter.py"     || fail "test_adapter.py MISSING"
[ -f "tests/test_chaos.py" ]                        && ok "test_chaos.py"       || fail "test_chaos.py MISSING"

echo ""
echo "─── Python Syntax ────────────────────────"
python -m py_compile engine/identity.py   && ok "engine/identity.py"   || fail "engine/identity.py SYNTAX ERROR"
python -m py_compile engine/store.py      && ok "engine/store.py"      || fail "engine/store.py SYNTAX ERROR"
python -m py_compile engine/graph.py      && ok "engine/graph.py"      || fail "engine/graph.py SYNTAX ERROR"
python -m py_compile engine/assembler.py  && ok "engine/assembler.py"  || fail "engine/assembler.py SYNTAX ERROR"
python -m py_compile engine/motifs.py     && ok "engine/motifs.py"     || fail "engine/motifs.py SYNTAX ERROR"
python -m py_compile adapters/engine.py   && ok "adapters/engine.py"   || fail "adapters/engine.py SYNTAX ERROR"

echo ""
echo "─── Quick Benchmark ─────────────────────"
if python self_check.py --adapter adapters.engine:Engine --quick > /tmp/sc_out.txt 2>&1; then
    ok "self_check.py --quick passed"
else
    fail "self_check.py --quick FAILED"
    tail -20 /tmp/sc_out.txt
fi

echo ""
echo "─── Unit Tests ──────────────────────────"
if python -m pytest tests/ -q --tb=short > /tmp/test_out.txt 2>&1; then
    NTESTS=$(grep -E "passed" /tmp/test_out.txt | tail -1 || echo "? tests")
    ok "Unit tests passed ($NTESTS)"
else
    fail "Unit tests FAILED"
    tail -30 /tmp/test_out.txt
fi

echo ""
echo "─── Chaos Scenario ──────────────────────"
if python -m pytest tests/test_chaos.py -v --tb=short > /tmp/chaos_out.txt 2>&1; then
    ok "Chaos scenario passed"
else
    fail "Chaos scenario FAILED"
    tail -30 /tmp/chaos_out.txt
fi

echo ""
echo "─── No Hardcoded Service Names ──────────"
if grep -r "svc-pay\|svc-bil\|svc-chk\|payments-svc\|billing-svc" engine/ adapters/ --include="*.py" > /dev/null 2>&1; then
    fail "Hardcoded service names found in engine/ or adapters/"
else
    ok "No hardcoded service names in engine/ or adapters/"
fi

echo ""
echo "─── Docker Build ────────────────────────"
if command -v docker &>/dev/null; then
    if docker build -t mini-anvil-validate . > /tmp/docker_out.txt 2>&1; then
        ok "Docker build succeeded"
    else
        fail "Docker build FAILED"
        tail -10 /tmp/docker_out.txt
    fi
else
    warn "Docker not available — skipping"
fi

echo ""
echo "=========================================="
echo " Results: ${PASS} passed, ${FAIL} failed"
if [ $FAIL -eq 0 ]; then
    echo -e " ${GREEN}🎉 SUBMISSION READY!${NC}"
else
    echo -e " ${RED}⚠️  Fix the failures above before submitting.${NC}"
fi
echo "=========================================="

exit $FAIL
