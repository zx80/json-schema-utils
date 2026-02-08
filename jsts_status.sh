#! /bin/bash

# provide JSON Schema Test Suite root directory from env, parameter or genua default
default_root="../dsv/json-model/tests/JSON-Schema-Test-Suite"
root_dir=${1:-${JSTS_ROOT:-$default_root}}

function err()
{
  local status=$1
  shift
  echo "$@" >&2
  exit $status
}

test -d "$root_dir" || err 1 "no such directory: $root_dir"

echo "# JSON Schema Test Suite Report"
echo
echo "JSTS version: \`$(pushd "$root_dir" > /dev/null 2>&1 && git log -1 | head -1 | cut -d' ' -f2)\`"
echo "JSU version: \`$(jsu-test-runner --version)\`"
echo "JMC version: \`$(jmc --version)\`"
echo

for draft in draft2020-12 draft2019-09 draft7 draft6 draft4 draft3 v1 latest ; do
  echo "## Results for _${draft}_"
  echo
  echo -n "$draft: " >&2

  test_dir="${root_dir}/tests/${draft}"
  test -d "$test_dir" || err 2 "no such case directory: $test_dir"

  # per case
  for file in ${test_dir}/*.json ; do
    test=${file#$test_dir}
    echo -n "- \`$test\`: "
    jsu-test-runner --resilient $file 2> /dev/null | tail -1 | sed -e 's/files=1 //'
    echo -n "." >&2
  done

  # and summary
  echo -n "- summary: "
  jsu-test-runner --resilient ${test_dir}/*.json 2> /dev/null | tail -1
  echo "." >&2

  echo
done
