#! /bin/bash

set -o pipefail

debug= err=/dev/null
# debug=1 err=jsts.err

# provide JSON Schema Test Suite root directory from env, parameter or genua default
default_root="../dsv/json-model/tests/JSON-Schema-Test-Suite"
root_dir=${1:-${JSTS_HOME:-$default_root}}

function err()
{
  local status=$1
  shift
  echo "$@" >&2
  exit $status
}

# globals: $debug $err $jsu_runner $jsu_opts
function process_dir()
{
  local name=$1 root=$2 dir=$3
  shift 3
  echo -n "$name: " >&2

  local status file test summary percent

  # per case
  for file in ${dir}/*.json ; do
    test=${file#$root/}
    echo -n "- \`$test\`: "
    [ "$debug" ] && echo "# command: $jsu_runner $jsu_opts $file" >> $err
    $jsu_runner $jsu_opts "$@" $file 2>> $err | tail -1 | sed -e 's/files=1 //'
    status=$?
    if [ $status -eq 0 ] ; then
      echo -n "."
    elif [ $status -eq 1 ] ; then
      echo -n ","
    else
      echo -n "*"
    fi >&2
  done

  # and summary with a full rerun
  echo -n "- summary: "
  summary=$($jsu_runner $jsu_opts "$@" ${dir}/*.json 2>> $err | tail -1)
  echo $summary
  percent="(${summary##* \(}"
  echo ". $percent" >&2

  echo
}

test -d "$root_dir" || err 1 "no such directory: $root_dir"

echo "# JSON Schema Test Suite Report"
echo
echo "Versions:"
echo
echo "- JSTS: \`$(pushd "$root_dir" > /dev/null 2>&1 && git log -1 | head -1 | cut -d' ' -f2)\`"
echo "- JSU: \`$(jsu-test-runner --version)\` (with Python backend)"
echo

if ! [ -d $root_dir/remotes ] ; then
  err 2 "remotes directory is missing"
fi

jsu_runner="jsu-test-runner --resilient --cache=. --map http://localhost:1234/=file://$root_dir/remotes/"

for draft in draft2020-12 draft2019-09 draft7 draft6 draft4 draft3 v1 ; do

  jsu_opts=""
  case $draft in
    draft7) jsu_opts+=" --schema-version 7" ;;
    draft6) jsu_opts+=" --schema-version 6" ;;
    draft4) jsu_opts+=" --schema-version 4" ;;
    draft3) jsu_opts+=" --schema-version 3" ;;
    # others should be retrieved automatically?
    *) ;;
  esac

  [ "$debug" ] && jsu_opts+=" --debug"

  test_dir="${root_dir}/tests/${draft}"
  test -d "$test_dir" || err 2 "no such case directory: $test_dir"

  [ "$debug" ] && echo "$jsu_runner $jsu_opts ..." >&2

  echo "## Results for _${draft}_"
  echo
  echo "Main test suite:"
  echo

  process_dir "$draft" "$test_dir" "$test_dir"

  format_dir="$test_dir/optional/format"
  if [ -d "$format_dir" ] ; then
    echo
    echo "Optional format tests:"
    echo
    process_dir "$draft/format" "$test_dir/optional" "$format_dir" --format
  fi
done
