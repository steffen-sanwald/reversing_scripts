#Rename functions based on logging function called
#@author RD Team of Conviso
#@category Conviso_Scripts
#@keybinding
#@menupath
#@toolbar


import ghidra.app.script.GhidraScript as GhidraScript
import ghidra.program.model.symbol.RefType as RefType
import ghidra.program.model.symbol.SymbolType as SymbolType
from ghidra.app.decompiler import DecompileOptions
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import json

current_program = getCurrentProgram()   # Gets the current program
monitor = ConsoleTaskMonitor()          # Handles monitor output to console
options = DecompileOptions()            # Configuration options for the decompiler
ifc = DecompInterface()                 # Interface to a single decompile process

ifc.setOptions(options)
ifc.openProgram(current_program)


def get_target_function(name):
    symbol = current_program.symbolTable.getExternalSymbol(name)
    if not symbol:
        return getFunction(name)
    thunk_address = symbol.object.functionThunkAddresses[0]
    for ref in getReferencesTo(thunk_address):
        if ref.getReferenceType() == RefType.COMPUTED_CALL:
            return getFunctionContaining(ref.getFromAddress())
    return None


def get_callers(function):
    address = function.getEntryPoint()
    callers = set()
    refs = getReferencesTo(address)
    for ref in refs:
        if ref.getReferenceType().isCall():
            caller = getFunctionContaining(ref.getFromAddress())
            if caller is None: continue
            callers.add(caller)
    return list(callers)



# Varnode.isConstant    - True if this varnode is just a constant number
# Varnode.getOffset     - The offset into the address space varnode is defined within
# Varnode.isUnique      - True if this varnode doesn't exist anywhere. A temporary variable
# Varnode.getDef        - Get the pcode op this varnode belongs to
# PcodeOp.getInput      - The i'th input varnode
# getDataContaining     - Get the defined data containing the specified address or null if no data exists
# Data.getValue         - Get the value of the data, it may be an address, a scalar, register or null if no value
# Varnode.getHigh       - Get the high level variable this varnode represents
# HighVariable.getName  - Get the name of the variable
# ARM-specific refactored script to resolve function arguments
def resolve_args(args):
    resolveds = []
    #print("args:"+str(args))
    for arg in args:
        if arg.isConstant():
            resolved = arg.getOffset()
        elif arg.isUnique():
            the_def = arg.getDef()
            constant_offset = the_def.getInput(0).getOffset()
            constant_addr = toAddr(constant_offset)
            data = getDataContaining(constant_addr)
            if data:
                resolved = data.getValue()
            else:
                resolved = data
        else:
            resolved = arg.getHigh().getName()
        resolveds.append(resolved)
    #print("Resolveds"+str(resolveds))
    return resolveds


def get_calls_from_all_callers(callers, callee):
    callers_info = []
    for caller in callers:
        caller_info = {
            'caller': {
                'name': caller.getName(),
                'address': caller.getEntryPoint()
            },
            'calls': get_calls_from_caller(caller, callee)
        }
        callers_info.append(caller_info)
    return callers_info


# decompileFunction                 - Decompile function
# DecompileResults.getHighFunction  - Get the high-level function structure associated with these decompilation results
# HighFunction.getPcodeOps          - Get all PcodeOps (alive or dead) ordered by SequenceNumber
# Ref: https://github.com/HackOvert/GhidraSnippets?tab=readme-ov-file#analyzing-function-call-arguments-at-cross-references
def get_calls_from_caller(caller, callee):
    calls = []
    res = ifc.decompileFunction(caller, 60, monitor)
    high_func = res.getHighFunction()
    if high_func:
        opiter = high_func.getPcodeOps()
        while opiter.hasNext():
            op = opiter.next()
            mnemonic = str(op.getMnemonic())
            #print("do i reach this"+mnemonic)
            if mnemonic == "CALL":
                inputs = op.getInputs()
                address = inputs[0].getAddress()
                # List of VarnodeAST types
                args = inputs[1:]
                #print("i should be printed")
                #print(inputs)
                if address == callee.getEntryPoint():
                    # get address of instruction this sequence belongs to
                    location = op.getSeqnum().getTarget()

                    call_info = {
                        'location': location,
                        'callee' : {
                            'name': callee.getName(),
                            'address': callee.getEntryPoint()
                        },
                        'args': resolve_args(args)
                    }
                    calls.append(call_info)
    #print("calls:"+str(calls))
    return calls


def get_real_name_candidates(callers_info, arg_num):
    with open("/tmp/results.csv", "w") as fp:
        fp.write("orig_funcname,log_command_name,log_content\n")
    callers_candidates = []
    for info in callers_info:
        names_candidates = set()
        caller_info = {'caller': info['caller']}
        for cur_call in info["calls"]:
            with open("/tmp/results.csv","a") as fp:
                fp.write(str(info["caller"]["name"]) + "," + str(cur_call["args"][2]) + "," + str(cur_call["args"][3].replace(",",".") + "\n"))
        for call in info['calls']:  names_candidates.add(call['args'][arg_num])
        caller_info['candidates'] = list(names_candidates)
        print("Realname Candidate:" + str(caller_info) + " " + str(call['args']))
        callers_candidates.append(caller_info)
    return callers_candidates


def rename_all(callers_candidates):
    total = len(callers_candidates)
    count = 0
    for callers_candidate in callers_candidates:
        current_name = callers_candidate['caller']['name']
        address  = callers_candidate['caller']['address']
        candidates = callers_candidate['candidates']
        if not current_name.startswith('FUN_'): continue
        if (len(candidates)) != 1:
            msg = "ERROR   - {} - more than 1 candidate - {}"
            print(msg.format(current_name, str(candidates)))
            continue
        function = getFunction(current_name)
        new_name = candidates[0]
        if not new_name:
            msg = "ERROR   - {} - candidate is None"
            print(msg.format(current_name))
            continue
        function.setName(new_name, ghidra.program.model.symbol.SourceType.USER_DEFINED)
        print("SUCCESS - {} renamed to {}".format(current_name, new_name))
        count += 1
    perc = (float(count) / float(total)) * 100.0
    print("From {} functions {} were renamed - {}% ".format(total, count, perc))


def rename_from_logging_function(function_name, arg_num):
    callee = get_target_function(function_name)
    callers = get_callers(callee)
    callers_info = get_calls_from_all_callers(callers, callee)
    callers_candidates = get_real_name_candidates(callers_info, arg_num)
    print(str(callers_candidates))
    #with open("/tmp/result.json","w") as fp:
    #    json.dump(callers_candidates,fp)
    with open("/tmp/result.log","w") as f:
        for cur_caller_candidate in callers_candidates:
            f.write(str(cur_caller_candidate)+"\r\n")
    #rename_all(callers_candidates)


def main():
    rename_from_logging_function('log_stuff', 2)


if __name__ == '__main__':
    main()
