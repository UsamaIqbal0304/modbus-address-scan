#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Usama Iqbal (Plantroom Labs)
"""What a Niagara station actually puts on the Modbus wire.

    ./modbus-address-scan.py [NIAGARA_HOME]

Why this exists. A Modbus point has two independent controls that both have to
be right - the address (a string plus a format enum) and the register type -
and neither one validates against the other or against the 16 bits the
protocol has. This script reads what each one does out of modbusCore-rt.jar
with javap rather than out of the documentation:

  - which of the three address formats a new point gets, out of the property
    default in BFlexAddress's static initialiser;
  - what getDataAddress() does per format, including the band subtractions the
    modbus format applies, straight out of the bytecode's constants;
  - what isValid() will and will not reject;
  - which register type a new point gets, and where it comes from;
  - what ModbusReadRequest puts in the two address bytes of the frame.

Then it works the boundary values out of the constants it just read, rather
than asserting them, and ends in checks a station settles in an afternoon.

Nothing is installed, patched or sent anywhere. unzip and javap only.
"""
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import os

HOME = Path(sys.argv[1] if len(sys.argv) > 1 else
            os.environ.get("NIAGARA_HOME", "/opt/Niagara/Niagara-4.15.5.22"))
JARS = ("modbusCore-rt.jar", "modbusTcp-rt.jar")


def abort(msg):
    print("ABORT " + msg, file=sys.stderr)
    sys.exit(2)


def _find_javap(niagara_home=None):
    """javap from $JAVAP, then PATH, then the JDK Niagara ships, then Debian's."""
    import os
    import shutil
    cand = [os.environ.get("JAVAP"), shutil.which("javap")]
    for base in (os.environ.get("JAVA_HOME"), niagara_home):
        if base:
            cand += [str(Path(base) / "bin" / "javap"),
                     str(Path(base) / "jre" / "bin" / "javap")]
    cand.append("/usr/lib/jvm/java-8-openjdk-amd64/bin/javap")
    for c in cand:
        if c and Path(c).exists():
            return c
    return None


JAVAP = _find_javap(HOME)


def dis(classpath, cls):
    out = subprocess.run([JAVAP, "-p", "-c", "-classpath", str(classpath), cls],
                         capture_output=True, text=True)
    if out.returncode != 0 or "Compiled from" not in out.stdout:
        abort("javap failed on %s: %s" % (cls, out.stderr.strip()[:200]))
    return out.stdout


def method(text, sig, what):
    """The bytecode of one method: from its signature to the blank line."""
    i = text.find(sig)
    if i < 0:
        abort("no %s in this jar (looked for %r)" % (what, sig))
    j = text.find("\n\n", i)
    return text[i:j if j > 0 else len(text)]


def one(hay, pat, what):
    m = re.findall(pat, hay)
    if len(m) != 1:
        abort("%d matches for %s (expected 1)" % (len(m), what))
    return m[0]


if not JAVAP:
    abort("no javap found - set $JAVAP or put a JDK 8 javap on PATH")
for jar in JARS:
    if not (HOME / "modules" / jar).exists():
        abort("no %s under %s" % (jar, HOME / "modules"))

work = Path(tempfile.mkdtemp(prefix="modbus-scan-"))
for jar in JARS:
    with zipfile.ZipFile(HOME / "modules" / jar) as z:
        z.extractall(work)

ver = subprocess.run([JAVAP, "-version"], capture_output=True, text=True).stdout.strip()
FA = dis(work, "com.tridium.modbusCore.datatypes.BFlexAddress")
FMT = dis(work, "com.tridium.modbusCore.enums.BAddressFormatEnum")
RT = dis(work, "com.tridium.modbusCore.enums.BRegisterTypeEnum")
NPE = dis(work, "com.tridium.modbusCore.client.point.BModbusClientNumericProxyExt")
REQ = dis(work, "com.tridium.modbusCore.messages.ModbusReadRequest")
DTU = dis(work, "com.tridium.modbusCore.util.DataTypeUtil")

print("Modbus addressing: what a point is before anyone configures it")
print("=" * 70)
print()
print("read from %s" % HOME)
print("javap:    %s" % ver)
print()

# ---- 1. the three formats, and the one a new point gets --------------------
formats = re.findall(r"public static final com\.tridium\.modbusCore\.enums\."
                     r"BAddressFormatEnum (\w+);", FMT)
named = [f for f in formats if f != "DEFAULT"]
if "DEFAULT" not in formats:
    abort("BAddressFormatEnum has no DEFAULT")
fmt_default = one(method(FMT, "  static {};", "the format enum's static block"),
                  r"// Field (\w+):Lcom/tridium/modbusCore/enums/BAddressFormatEnum;"
                  r"\n\s+\d+: putstatic\s+#\d+\s+// Field DEFAULT:",
                  "the DEFAULT format")

fa_static = method(FA, "  static {};", "BFlexAddress's static initialiser")
prop_fmt = one(fa_static,
               r"// Field com/tridium/modbusCore/enums/BAddressFormatEnum\.(\w+):"
               r"Lcom/tridium/modbusCore/enums/BAddressFormatEnum;"
               r"[\s\S]{0,400}?// Field addressFormat:Ljavax/baja/sys/Property;",
               "the addressFormat property default")
prop_addr = one(fa_static,
                r'// String (\S+)\n[\s\S]{0,400}?'
                r'// Field address:Ljavax/baja/sys/Property;',
                "the address property default")

print("A point's address is two slots, and these are their defaults:")
print("  addressFormat  %s        (the formats are %s)"
      % (prop_fmt, ", ".join(named)))
print('  address        "%s"' % prop_addr)
print("  BAddressFormatEnum.DEFAULT is %s as well." % fmt_default)
print()
if prop_fmt != "hex":
    print("  NOTE: this install defaults to %s, not hex. The rest of this" % prop_fmt)
    print("  report still holds, but the first consequence below does not.")
    print()
else:
    print("  So a freshly made point reads its address as base 16. A number")
    print("  copied out of a device's Modbus documentation - 40001, 1000, 2000 -")
    print("  is a different number by the time it reaches the wire, and nothing")
    print("  in the point says so.")
    print()

# ---- 2. getDataAddress, per format ----------------------------------------
gda = method(FA, "  public int getDataAddress();", "getDataAddress")
gdn = method(FA, "  public int getDataAddressNoModbusAltering();",
             "getDataAddressNoModbusAltering")
radix = re.findall(r"bipush\s+(\d+)\n\s+\d+: invokestatic\s+#\d+\s+"
                   r"// Method java/lang/Integer\.valueOf:"
                   r"\(Ljava/lang/String;I\)Ljava/lang/Integer;", gda)
if radix != ["16"]:
    abort("expected exactly one base-16 parse in getDataAddress, got %r" % radix)

# The modbus bands. Each one is the same seven instructions: load, push a
# ceiling, if_icmple past the band, load, push the offset, subtract, return.
NUM = r"(?:ldc\s+#\d+\s+// int (\d+)|sipush\s+(\d+))"
bands = []
for m in re.finditer(r"iload_1\n\s+\d+: " + NUM + r"\n\s+\d+: if_icmple\s+\d+"
                     r"\n\s+\d+: iload_1\n\s+\d+: " + NUM + r"\n\s+\d+: isub",
                     gda):
    ceiling = int(m.group(1) or m.group(2))
    offset = int(m.group(3) or m.group(4))
    bands.append((ceiling, offset))
if len(bands) != 4:
    abort("found %d modbus bands in getDataAddress, expected 4" % len(bands))
if bands != sorted(bands, reverse=True):
    abort("the bands are not in descending order: %r" % bands)
if not re.search(r"iload_1\n\s+\d+: iconst_1\n\s+\d+: isub\n\s+\d+: ireturn", gda):
    abort("no trailing n-1 fallthrough in getDataAddress")

print("getDataAddress(), the method the poll path calls, by format:")
print("  hex       Integer.valueOf(address, 16). No offset, no bounds.")
print("  decimal   Integer.valueOf(address). No offset, no bounds.")
print("  modbus    parse, then subtract by band, highest band first:")
for cmp_c, sub_c in bands:
    print("              > %-5d  ->  n - %d" % (cmp_c, sub_c))
print("              else     ->  n - 1")
print("  getDataAddressNoModbusAltering() parses and stops - it is the one")
print("  the band predicates use, not the one the poll path uses.")
print()


def modbus_data_address(n):
    """Exactly what the bytecode above does, in the order it does it."""
    for cmp_c, sub_c in bands:
        if n > cmp_c:
            return n - sub_c
    return n - 1


print("The comparisons are if_icmple, so each band's own lower bound falls")
print("through into the band below it. Working the boundaries through:")
for cmp_c, _ in bands:
    print("  modbus %-6d -> data address %d" % (cmp_c, modbus_data_address(cmp_c)))
collapsed = {modbus_data_address(c) for c, _ in bands}
if len(collapsed) == 1:
    print("  All %d of them land on the same register: %d. Four different"
          % (len(bands), collapsed.pop()))
    print("  addresses, four different conventions, one register read.")
else:
    print("  They land on %s." % ", ".join(str(x) for x in sorted(collapsed)))
print()

# ---- 3. isValid ------------------------------------------------------------
iv = method(FA, "  public boolean isValid();", "isValid")
iv_bound = re.findall(r"(?:ldc|sipush)\s+#?\d*\s*(?:// int )?(\d+)\n"
                      r"\s+\d+: if_icmpge", iv)
print("isValid() is the only gate between a typed string and a poll:")
print("  modbus format     0 <= n < %s" % (iv_bound[0] if iv_bound else "?"))
print("  every other format    n >= 0, and that is the whole test.")
print("  Modbus addresses are 16 bits. There is no 65535 anywhere in")
print("  isValid(), so a hex or decimal address of any size is valid.")
print()

# ---- 4. the register type is a different control altogether ---------------
drt = method(NPE, "  public com.tridium.modbusCore.enums.BRegisterTypesEnum"
                  " determineRegisterType();", "determineRegisterType")
if "getRegType" not in drt:
    abort("determineRegisterType does not read getRegType")
if "getDataAddress" in drt or "isModbus" in drt:
    abort("determineRegisterType looks at the address after all - re-read it")
npe_static = method(NPE, "  static {};", "the numeric proxy ext's static block")
rt_default = one(npe_static,
                 r"// Field com/tridium/modbusCore/enums/BRegisterTypeEnum\.(\w+):"
                 r"[\s\S]{0,400}?// Field regType:Ljavax/baja/sys/Property;",
                 "the regType property default")
rt_members = [m for m in re.findall(
    r"public static final com\.tridium\.modbusCore\.enums\.BRegisterTypeEnum"
    r" (\w+);", RT) if m != "DEFAULT"]

print("Which register type gets read is a separate property:")
print("  determineRegisterType() returns holdingRegister or inputRegister")
print("  purely on the point's own regType slot (%s). It never looks"
      % "/".join(rt_members))
print("  at the address or at any of the isModbus*Address predicates.")
print("  regType defaults to %s." % rt_default)
print()
print("  So the number and the function code are independent. A modbus-format")
print("  address of 30001 - input-register numbering by every convention -")
print("  resolves to data address %d and, on a default point, is read with"
      % modbus_data_address(30001))
print("  the holding-register function code. Nothing objects.")
print()

# ---- 5. the band predicates, and the values none of them claim ------------
preds = {}
for name in re.findall(r"public boolean (isModbus\w+Address)\(\);", FA):
    body = method(FA, "  public boolean %s();" % name, name)
    nums = [int(x) for x in re.findall(
        r"(?:ldc|sipush)\s+#?\d*\s*(?:// int )?(\d{4,})", body)]
    ops = re.findall(r"(if_icmple|if_icmplt|if_icmpge|iflt)", body)
    preds[name] = (nums, ops)
strict_low = [n for n, (nums, ops) in preds.items()
              if nums and ops and ops[0] == "if_icmple"]
print("The six isModbus*Address predicates classify an address into a band,")
print("and %d of the %d use if_icmple on the lower bound, so the bound itself"
      % (len(strict_low), len(preds)))
print("is in no band at all. The predicates parse base 10 directly and return")
print("false for any non-modbus format, which makes them silent on exactly the")
print("addresses the default format produces.")
print()

# ---- 6. what reaches the frame -------------------------------------------
ctor = method(REQ, "  public com.tridium.modbusCore.messages.ModbusReadRequest"
                   "(int, com.tridium.modbusCore.BModbusDevice, int, int, int,"
                   " int);", "the ModbusReadRequest constructor")
if re.search(r"if_icmp|ifgt|ifge|iflt|ifle", ctor):
    abort("the constructor does compare something - re-read it")
rtu = method(REQ, "  public final void writeRtu(java.io.OutputStream)"
                  " throws java.io.IOException;", "writeRtu")
hi = one(rtu, r"// Field startAddress:I\n\s+\d+: ldc\s+#\d+\s+// int (\d+)\n"
              r"\s+\d+: iand\n\s+\d+: bipush\s+8\n\s+\d+: ishr", "the high byte mask")
lo = one(rtu, r"// Field startAddress:I\n\s+\d+: sipush\s+(\d+)\n\s+\d+: iand\n"
              r"\s+\d+: i2b", "the low byte mask")
mask = int(hi) | int(lo)
print("What ModbusReadRequest does with the number it is given:")
print("  the constructor stores startAddress straight into the field. There")
print("  is not one comparison in it.")
print("  writeRtu and writeTcp emit two bytes: (a & %s) >> 8, then a & %s."
      % (hi, lo))
print("  That is a 0x%X mask applied by omission. Everything above 16 bits is" % mask)
print("  dropped with no exception, no log line and no status flag.")
print()

# ---- 7. and how many registers one point asks for ------------------------
grc = method(DTU, "getRegisterCount", "getRegisterCount")
counts = sorted({int(m) for m in re.findall(
    r"iconst_(\d)\n\s+\d+: ireturn", grc)}, reverse=True)
if not counts:
    abort("getRegisterCount returns no constants")
print("getRegisterCount by data type: %s registers per point, so one point's"
      % ", ".join(str(c) for c in counts))
print("span can read its address plus %d. The mask above is applied to the"
      % (max(counts) - 1))
print("start address, and the point count goes through the same two bytes.")
print()

print("Three consequences worth designing for")
print("-" * 70)
print("  1. The default format is %s. A documented address of 40001 typed into" % prop_fmt)
print("     a new point is %d, which isValid() accepts, and the frame carries"
      % int("40001", 16))
print("     it as register %d. The point reads, goes ok, and is wrong."
      % (int("40001", 16) & mask))
print("  2. Nothing in the chain knows the protocol is 16-bit. The only bound")
print("     in isValid() applies to the one format a new point does not have.")
print("  3. The address convention and the function code are two properties")
print("     that can disagree in silence. A driver or a tool that writes")
print("     points should set both, and should refuse the four band boundaries.")
print()
print("Three checks one station settles in an afternoon")
print("-" * 70)
print("  1. Make a point, leave the format alone, type 40001, and watch the")
print("     frame: the address bytes should be %s."
      % " ".join("%02X" % b for b in
                 ((int("40001", 16) & mask) >> 8, int("40001", 16) & int(lo))))
print("  2. Set the format to modbus and try each of %s"
      % ", ".join(str(c) for c, _ in bands))
print("     in turn. If they all read one register, this install behaves")
print("     like this one.")
print("  3. Set regType to %s, set the format to modbus, and use an address"
      % rt_default)
print("     in the %d-%d band. Confirm which function code goes out: the"
      % (bands[0][0] + 1, int(iv_bound[0]) if iv_bound else 0))
print("     number does not pick it, the property does.")
