# modbus-address-scan

What a Niagara station actually puts on the Modbus wire, read out of the
driver's own bytecode.

One Python file, standard library only. It reads `modbusCore-rt.jar` and
`modbusTcp-rt.jar` from a Niagara installation with `javap`, works the
boundary values out of the constants it finds, and prints the checks that
settle it on a real station.

```
./modbus-address-scan.py [NIAGARA_HOME]
```

## Why this exists

A Modbus point has two independent controls that both have to be right - the
address, which is a string plus a format enum, and the register type - and
neither one validates against the other, or against the 16 bits the protocol
has.

The short version of what that produces: **the address format property on a
new point defaults to hex.** A register documented as 40001 and typed in as
40001 is read as hex, becomes 262145, and `isValid()` accepts it, because the
only bound it applies belongs to a format the new point does not have. Nothing
downstream knows the protocol is 16 bits: `ModbusReadRequest` stores the number
and emits two bytes, so everything above 16 bits is dropped by omission, with
no exception, no log line and no status flag. The frame goes out asking for
register 1. The point reads, the status is ok, and the value belongs to another
register entirely.

## What it reads, and where from

- Which of the three address formats a new point gets, from the property
  default in `BFlexAddress`'s static initialiser.
- What `getDataAddress()` does per format, including the band subtractions the
  modbus format applies, straight out of the bytecode's constants.
- What `isValid()` will and will not reject.
- Which register type a new point gets, and where it comes from.
- What `ModbusReadRequest` puts in the two address bytes of the frame.

## Read first: what it does and does not touch

**It never speaks Modbus and never opens a socket.** It unzips jars and runs
`javap`. Nothing is installed, patched, written to a station or sent anywhere.

It needs a Niagara installation to read and a `javap` from a JDK 8. It looks
for `javap` in `$JAVAP`, then on `PATH`, then under `$JAVA_HOME` and the
Niagara install, then in Debian's default location. The install to read comes
from the first argument or `$NIAGARA_HOME`.

**The output below was measured against Niagara 4.15.5.22.** Another version
may differ, and that is the point - rerun it against yours rather than
trusting this page.

## Running it

```
$ ./modbus-address-scan.py
Modbus addressing: what a point is before anyone configures it
======================================================================

read from /opt/Niagara/Niagara-4.15.5.22
javap:    1.8.0_504

A point's address is two slots, and these are their defaults:
  addressFormat  hex        (the formats are hex, decimal, modbus)
  address        "0"
  BAddressFormatEnum.DEFAULT is hex as well.

  So a freshly made point reads its address as base 16. A number
  copied out of a device's Modbus documentation - 40001, 1000, 2000 -
  is a different number by the time it reaches the wire, and nothing
  in the point says so.

getDataAddress(), the method the poll path calls, by format:
  hex       Integer.valueOf(address, 16). No offset, no bounds.
  decimal   Integer.valueOf(address). No offset, no bounds.
  modbus    parse, then subtract by band, highest band first:
              > 40000  ->  n - 40001
              > 30000  ->  n - 30001
              > 20000  ->  n - 20001
              > 10000  ->  n - 10001
              else     ->  n - 1
  getDataAddressNoModbusAltering() parses and stops - it is the one
  the band predicates use, not the one the poll path uses.

The comparisons are if_icmple, so each band's own lower bound falls
through into the band below it. Working the boundaries through:
  modbus 40000  -> data address 9999
  modbus 30000  -> data address 9999
  modbus 20000  -> data address 9999
  modbus 10000  -> data address 9999
  All 4 of them land on the same register: 9999. Four different
  addresses, four different conventions, one register read.

isValid() is the only gate between a typed string and a poll:
  modbus format     0 <= n < 50000
  every other format    n >= 0, and that is the whole test.
  Modbus addresses are 16 bits. There is no 65535 anywhere in
  isValid(), so a hex or decimal address of any size is valid.

Which register type gets read is a separate property:
  determineRegisterType() returns holdingRegister or inputRegister
  purely on the point's own regType slot (holding/input). It never looks
  at the address or at any of the isModbus*Address predicates.
  regType defaults to holding.

  So the number and the function code are independent. A modbus-format
  address of 30001 - input-register numbering by every convention -
  resolves to data address 0 and, on a default point, is read with
  the holding-register function code. Nothing objects.

The six isModbus*Address predicates classify an address into a band,
and 3 of the 6 use if_icmple on the lower bound, so the bound itself
is in no band at all. The predicates parse base 10 directly and return
false for any non-modbus format, which makes them silent on exactly the
addresses the default format produces.

What ModbusReadRequest does with the number it is given:
  the constructor stores startAddress straight into the field. There
  is not one comparison in it.
  writeRtu and writeTcp emit two bytes: (a & 65280) >> 8, then a & 255.
  That is a 0xFFFF mask applied by omission. Everything above 16 bits is
  dropped with no exception, no log line and no status flag.

getRegisterCount by data type: 4, 3, 2, 1 registers per point, so one point's
span can read its address plus 3. The mask above is applied to the
start address, and the point count goes through the same two bytes.

Three consequences worth designing for
----------------------------------------------------------------------
  1. The default format is hex. A documented address of 40001 typed into
     a new point is 262145, which isValid() accepts, and the frame carries
     it as register 1. The point reads, goes ok, and is wrong.
  2. Nothing in the chain knows the protocol is 16-bit. The only bound
     in isValid() applies to the one format a new point does not have.
  3. The address convention and the function code are two properties
     that can disagree in silence. A driver or a tool that writes
     points should set both, and should refuse the four band boundaries.

Three checks one station settles in an afternoon
----------------------------------------------------------------------
  1. Make a point, leave the format alone, type 40001, and watch the
     frame: the address bytes should be 00 01.
  2. Set the format to modbus and try each of 40000, 30000, 20000, 10000
     in turn. If they all read one register, this install behaves
     like this one.
  3. Set regType to holding, set the format to modbus, and use an address
     in the 40001-50000 band. Confirm which function code goes out: the
     number does not pick it, the property does.
```

## The same finding, written up

The output above, the four address formats, the band boundaries that resolve to the same register, and the three checks that settle it on a real station, is also a page: <https://plantroomlabs.com/tools/modbus-address-scan/>. It carries this run, the download with its size and SHA-256, and the note explaining the reasoning.

## Licence

MIT. Written by Usama Iqbal at [Plantroom Labs](https://plantroomlabs.com).
