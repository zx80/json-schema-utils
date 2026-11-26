#! /bin/bash

set -o pipefail

debug= err=/dev/null
# debug=1 err=jsts.err

# provide JSON Schema Test Suite root directory from env, parameter or genua default
default_root="../json-model/tests/JSON-Schema-Test-Suite"
root_dir=${1:-${JSTS_HOME:-$default_root}}
cache_dir=.cache

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

  # start trace
  echo -n "$name: " >&2

  local status file test summary percent

  # per case
  for file in $(ls ${dir}/*.json | sort) ; do
    test=${file#$root/}
    [ "$debug" ] && echo "# command: $jsu_runner $jsu_opts $file" >> $err
    output=$($jsu_runner $jsu_opts "$@" $file 2>> $err | tail -1 | sed -e 's/files=1 //')
    status=$?
    # only output if something to show
    if [ "$output" ] ; then
      echo "- \`$test\`: $output"
      # trace
      if [ $status -eq 0 ] ; then
        echo -n "."
      elif [ $status -eq 1 ] ; then
        echo -n "/"
      else
        echo -n "*"
      fi >&2
    else
      echo -n "_" >&2
    fi
  done

  # and summary with a full rerun
  echo -n "- **summary**: "
  summary=$($jsu_runner $jsu_opts "$@" ${dir}/*.json 2>> $err | tail -1)
  echo $summary
  percent="(${summary##* \(}"
  echo ". $percent" >&2

  echo
}

for sub_dir in "" "/validation" "/validation/tests" ; do
  test -d "$root_dir$sub_dir" || err 1 "no such directory: $root_dir$sub_dir"
done

echo "# JSON Schema Test Suite Report"
echo
echo "Versions:"
echo
echo "- JSTS: \`$(pushd "$root_dir" > /dev/null 2>&1 && git log -1 | head -1 | cut -d' ' -f2)\`"
echo "- JSU: \`$(jsu runner --version)\` (Python backend)"
echo
echo "Note about \`format\` with the Python backend:"
echo
echo "- still searching for a good _hostname_ validator."
echo "- checking for _emacscript regex_ intricacies will only ever work with JavaScript."
echo "- draft3 allows time without a timezone, whereas later drafts do not"
echo

mkdir -p "$cache_dir"
test -d "$cache_dir" || err 3 "no such directory: $cache_dir"

jsu_runner="jsu runner --resilient --cache=$cache_dir"

function jsdraft()
{
  case $1 in
    10) echo "draft-next" ;;
    9) echo "draft2020-12" ;;
    8) echo "draft2019-09" ;;
    *) echo "draft$1" ;;
  esac
}

for draft in 9 8 7 6 4 3 10 ; do

  jsu_opts=" --schema-version $draft"
  sdraft=$(jsdraft $draft)

  [ "$debug" ] && jsu_opts+=" --debug"

  test_dir="${root_dir}/validation/tests"
  test -d "$test_dir" || err 4 "no such tests directory: $test_dir"

  [ "$debug" ] && echo "$jsu_runner $jsu_opts ..." >&2

  echo "## Results for _${sdraft}_"
  echo

  echo "Format annotations:"
  echo
  process_dir "$sdraft" "$test_dir" "$test_dir" --no-format

  echo "Format assertions:"
  echo
  process_dir "$sdraft/format" "$test_dir" "$test_dir" --format --tagged-only
done
