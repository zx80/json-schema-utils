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
echo "JSU (front) version: \`$(jsu-test-runner --version)\`"
echo "JMC (back) version: \`$(jmc --version)\`"
echo

jsu_runner="jsu-test-runner --resilient"

for draft in draft2020-12 draft2019-09 draft7 draft6 draft4 draft3 v1 latest ; do
  echo "## Results for _${draft}_"
  echo
  echo -n "$draft: " >&2

  jsu_opts=""
  case $draft in
    draft7) jsu_opts+=" --schema-version 7" ;;
    draft6) jsu_opts+=" --schema-version 6" ;;
    draft4) jsu_opts+=" --schema-version 4" ;;
    draft3) jsu_opts+=" --schema-version 3" ;;
    *) ;;
  esac

  test_dir="${root_dir}/tests/${draft}"
  test -d "$test_dir" || err 2 "no such case directory: $test_dir"

  # per case
  for file in ${test_dir}/*.json ; do
    test=${file#$test_dir}
    echo -n "- \`$test\`: "
    $jsu_runner $jsu_opts $file 2> /dev/null | tail -1 | sed -e 's/files=1 //'
    echo -n "." >&2
  done

  # and summary
  echo -n "- summary: "
  summary=$($jsu_runner $jsu_opts ${test_dir}/*.json 2> /dev/null | tail -1)
  echo $summary
  percent="(${summary##* \(}"
  echo ". $percent" >&2

  echo
done
